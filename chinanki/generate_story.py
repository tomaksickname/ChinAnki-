"""
Generate a story via DeepSeek, validate, enrich, rate SRS, save.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests
from pypinyin import pinyin as pypinyin_pinyin, Style

from . import config
from . import state as state_mod
from .srs import get_today_cards, rate_card
from .vocab import lookup as vocab_lookup
from .prompts import SYSTEM_STORY, build_story_prompt
from .validate_story import validate
from .gloss_clean import clean_gloss


_GLOSS_OVERRIDES = {
    "他": "he; him",
    "她": "she; her",
    "它": "it",
    "他们": "they; them",
    "她们": "they; them (female)",
    "它们": "they; them (neuter)",
}


def call_deepseek(system: str, user: str, temperature: float = 1.0,
                  max_tokens: int = 8000, timeout: int = 180) -> str:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(config.DEEPSEEK_URL, json=payload, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"DeepSeek HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    finish_reason = data["choices"][0].get("finish_reason", "")
    usage = data.get("usage", {})

    if os.environ.get("CHINANKI_DEBUG_RAW"):
        config.ensure_dirs()
        debug_path = config.STORIES_DIR / "_last_raw.txt"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(f"# finish_reason={finish_reason}\n")
            f.write(f"# usage={usage}\n")
            f.write(f"# content_length={len(content)}\n")
            f.write("---\n")
            f.write(content)
        print(f"  [debug] finish_reason={finish_reason}  usage={usage}  len={len(content)}")

    if finish_reason == "length":
        print(f"  WARN: response truncated (finish_reason=length)")

    return content


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_loose(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        s = text.find("{")
        e_pos = text.rfind("}")
        if s != -1 and e_pos != -1 and e_pos > s:
            try:
                return json.loads(text[s:e_pos + 1])
            except json.JSONDecodeError:
                pass
        raise e


def _pool_hanzi(st) -> set:
    return {e.hanzi for e in state_mod.free_pool(st)}


def _is_punct(h: str) -> bool:
    if not h:
        return True
    for ch in h:
        if "\u4e00" <= ch <= "\u9fff":
            return False
    return True


@lru_cache(maxsize=4096)
def _fallback_pinyin(hanzi: str) -> str:
    if not hanzi:
        return ""
    try:
        result = pypinyin_pinyin(hanzi, style=Style.TONE)
        syllables = [s[0] for s in result if s]
        return " ".join(syllables)
    except Exception:
        return ""


def enrich_story(story: Dict[str, Any]) -> None:
    for sent in story.get("sentences", []):
        raw_words = sent.get("words", [])
        enriched = []
        for h in raw_words:
            if not isinstance(h, str):
                continue
            if _is_punct(h):
                enriched.append({
                    "hanzi": h, "pinyin": "", "english": "",
                    "in_list": True, "punct": True,
                })
                continue
            entry = vocab_lookup(h)
            if h in _GLOSS_OVERRIDES:
                english = _GLOSS_OVERRIDES[h]
            elif entry is not None:
                english = clean_gloss(entry.english)
            else:
                english = ""
            if entry is not None:
                py = entry.pinyin or _fallback_pinyin(h)
                enriched.append({
                    "hanzi": h,
                    "pinyin": py,
                    "english": english,
                    "in_list": True,
                    "rank": entry.rank,
                })
            else:
                enriched.append({
                    "hanzi": h,
                    "pinyin": _fallback_pinyin(h),
                    "english": english,
                    "in_list": False,
                })
        sent["words"] = enriched


def generate_once(
    st: Dict[str, Any],
    user_topic: str,
    length: int,
    range_pct: int,
    toggle: int,
    verbose: bool = True,
) -> Tuple[Optional[Dict[str, Any]], List[str], List[str], List[str], Dict[str, Any]]:
    ph = state_mod.phase(st)
    today = get_today_cards(st, toggle)
    new_candidates = today["new"]
    due_entries = today["due"]
    free_pool_entries = today["free"]

    if verbose:
        print(f"  phase={ph}  candidates={len(new_candidates)}  "
              f"DUE={len(due_entries)}  FREE={len(free_pool_entries)}")

    prompt = build_story_prompt(
        new_candidates, due_entries, free_pool_entries,
        target_length=length, range_pct=range_pct,
        user_topic=user_topic,
        phase=ph,
        toggle=toggle,
    )
    if verbose:
        print(f"  calling DeepSeek (length={length})...")
    t0 = time.time()
    raw = call_deepseek(SYSTEM_STORY, prompt)
    if verbose:
        print(f"  got {len(raw)} chars in {time.time()-t0:.1f}s")

    try:
        story = parse_json_loose(raw)
    except Exception as e:
        return None, [f"JSON parse: {e}"], [], [], {}

    result = validate(
        story,
        new_entries=[e.hanzi for e in new_candidates],
        due_words=[e.hanzi for e in due_entries],
        pool_hanzi=_pool_hanzi(st),
        target_length=length,
        range_pct=range_pct,
        phase=ph,
        toggle=toggle,
        min_new_reps=1,
    )
    if result["warnings"] and verbose:
        for w in result["warnings"]:
            print(f"  WARN: {w}")
    if not result["ok"]:
        return None, result["errors"], [], [], result

    enrich_story(story)

    picks = result["stats"].get("new_picks_used", [])
    return story, [], picks, [e.hanzi for e in due_entries], result


def save_story(
    st: Dict[str, Any],
    story: Dict[str, Any],
    new_picks: List[str],
    due_hanzi: List[str],
    toggle: int,
    user_topic: str,
    target_length: int,
    range_pct: int,
    first_today: bool,
    validation_result: Dict[str, Any],
) -> Dict[str, Any]:
    now = datetime.now()

    if first_today:
        for h in new_picks:
            for _ in range(3):
                rate_card(st, h, "good", now=now)
        for h in due_hanzi:
            rate_card(st, h, "good", now=now)
        state_mod.freeze_today(
            st,
            new_quota=toggle,
            new_words=new_picks,
            due_words=due_hanzi,
        )
        state_mod.save_state(st)

    story_id = now.strftime("%Y-%m-%dT%H%M%S")
    record = {
        "id": story_id,
        "generated_at": now.isoformat(),
        "phase": state_mod.phase(st),
        "topic": story.get("topic", ""),
        "user_topic": user_topic,
        "target_length": target_length,
        "range_pct": range_pct,
        "toggle": toggle,
        "first_today": first_today,
        "new_words": new_picks,
        "due_words": due_hanzi,
        "free_bound": state_mod.free_bound(st),
        "title_english": story.get("title_english", "") or story.get("topic", ""),
        "title_hanzi": story.get("title_hanzi", ""),
        "title_pinyin": story.get("title_pinyin", ""),
        "sentences": story.get("sentences", []),
        "wishlist": validation_result.get("wishlist", []),
        "stats": validation_result.get("stats", {}),
        "target_minutes": 0,
    }
    config.ensure_dirs()
    out = config.STORIES_DIR / f"{story_id}.json"
    tmp = out.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    tmp.replace(out)
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="")
    ap.add_argument("--length", type=int, default=config.DEFAULT_LENGTH)
    ap.add_argument("--range", type=int, default=config.DEFAULT_RANGE_PCT)
    ap.add_argument("--new", type=int, default=config.DEFAULT_NEW_PER_DAY)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    st = state_mod.load_state()
    ph = state_mod.phase(st)

    if args.dry_run:
        today = get_today_cards(st, args.new)
        prompt = build_story_prompt(
            today["new"], today["due"], today["free"],
            target_length=args.length, range_pct=args.range,
            user_topic=args.topic, phase=ph, toggle=args.new,
        )
        print("=== SYSTEM ===")
        print(SYSTEM_STORY)
        print()
        print("=== USER ===")
        print(prompt)
        return 0

    first_today = not bool(state_mod.get_frozen_today(st))
    print(f"Phase: {ph}")
    print(f"First generation today: {first_today}")
    print(f"Topic: {args.topic!r}  Length: {args.length}+/-{args.range}%  Toggle: {args.new}")
    print()

    attempt_lengths = [
        args.length,
        min(500, int(args.length * 1.15)),
        min(500, int(args.length * 1.30)),
    ]
    last_errors: List[str] = []
    story: Optional[Dict[str, Any]] = None
    new_picks: List[str] = []
    due_hanzi: List[str] = []
    used_length = args.length
    validation_result: Dict[str, Any] = {}

    for attempt in range(1, config.MAX_RETRIES + 1):
        length = attempt_lengths[min(attempt - 1, len(attempt_lengths) - 1)]
        print(f"Attempt {attempt}/{config.MAX_RETRIES}  length={length}")
        story, errors, new_picks, due_hanzi, validation_result = generate_once(
            st, user_topic=args.topic,
            length=length, range_pct=args.range, toggle=args.new,
        )
        if story is not None:
            print("  valid")
            used_length = length
            break
        print(f"  {len(errors)} error(s):")
        for e in errors[:12]:
            print(f"     - {e}")
        last_errors = errors
        print()

    if story is None:
        print("All attempts failed. Last errors:")
        for e in last_errors:
            print(f"  - {e}")
        return 1

    if args.no_save:
        print()
        print("(no-save) valid, not rated/persisted")
        print(f"NEW picks (used): {new_picks}")
        wl = validation_result.get("wishlist", [])
        if wl:
            print(f"Wishlist ({len(wl)} out-of-pool words):")
            for w in wl[:20]:
                in_list = "IN LIST" if w["in_freq_list"] else "NOT IN LIST"
                rank = f"rank {w['rank']}" if w["rank"] else "—"
                print(f"  {w['hanzi']:6} x{w['count']}  {in_list}  {rank}")
        print()
        print(json.dumps(story, ensure_ascii=False, indent=2)[:2500])
        return 0

    print()
    print("Saving...")
    rec = save_story(
        st, story, new_picks, due_hanzi,
        toggle=args.new, user_topic=args.topic,
        target_length=used_length, range_pct=args.range,
        first_today=first_today,
        validation_result=validation_result,
    )
    print(f"  id:       {rec['id']}")
    print(f"  title:    {rec['title_hanzi']} ({rec['title_pinyin']})")
    print(f"  english:  {rec['title_english']}")
    print(f"  NEW:      {len(rec['new_words'])}  {rec['new_words']}")
    print(f"  DUE:      {len(rec['due_words'])}")
    print(f"  phase:    {rec['phase']}")
    if rec.get("wishlist"):
        print(f"  wishlist: {len(rec['wishlist'])} words")
        for w in rec["wishlist"][:10]:
            in_list = "IN" if w["in_freq_list"] else "OUT"
            print(f"    {w['hanzi']:6} x{w['count']}  {in_list}")
    print(f"  saved to: {config.STORIES_DIR / (rec['id'] + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
