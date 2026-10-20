"""
Validate a story returned by DeepSeek.

Unused NEW picks and unused DUE words are soft failures (warnings, not
errors) — they get dropped from the rating downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .vocab import in_list as vocab_in_list, lookup as vocab_lookup


def validate(
    story: Dict[str, Any],
    new_entries: List[str],
    due_words: List[str],
    pool_hanzi: set,
    target_length: int,
    range_pct: int,
    phase: int = 1,
    toggle: int = 10,
    min_new_reps: int = 1,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    out_of_pool: Dict[str, int] = {}

    if not isinstance(story.get("sentences"), list) or not story["sentences"]:
        return {"ok": False, "errors": ["story has no sentences"],
                "warnings": [], "stats": {}, "out_of_pool": {}, "wishlist": []}

    # ---- NEW picks ----
    if phase == 1:
        picks = story.get("new_words")
        if not isinstance(picks, list):
            errors.append("missing top-level 'new_words' array (Phase 1 requires it)")
            picks = []
        else:
            seen = set()
            dedup = []
            for p in picks:
                if p not in seen:
                    seen.add(p)
                    dedup.append(p)
            picks = dedup
            candidate_set = set(new_entries)
            invalid = [p for p in picks if p not in candidate_set]
            for p in invalid:
                warnings.append(f"NEW pick '{p}' not in candidate set (dropped)")
            picks = [p for p in picks if p in candidate_set]
        new_words = picks
    else:
        new_words = list(new_entries)

    new_set = set(new_words)
    allowed = set(pool_hanzi) | new_set

    total_chars = 0

    # ---- Concatenation + membership ----
    for si, sent in enumerate(story["sentences"]):
        sent_hanzi = sent.get("hanzi", "")
        words = sent.get("words", [])
        if not isinstance(words, list) or not words:
            errors.append(f"sentence {si}: no words[]")
            continue
        if not all(isinstance(w, str) for w in words):
            errors.append(f"sentence {si}: words[] must be an array of strings")
            continue
        joined = "".join(words)
        if joined != sent_hanzi:
            errors.append(
                f"sentence {si}: concatenation mismatch\n"
                f"  words: {joined}\n"
                f"  hanzi: {sent_hanzi}"
            )
        for h in words:
            if len(h) == 1 and not ("\u4e00" <= h <= "\u9fff"):
                continue
            total_chars += len(h)
            if h not in allowed:
                out_of_pool[h] = out_of_pool.get(h, 0) + 1

    # ---- Word counts ----
    counts: Dict[str, int] = {}
    for sent in story["sentences"]:
        for h in sent.get("words", []):
            if not isinstance(h, str):
                continue
            if len(h) == 1 and not ("\u4e00" <= h <= "\u9fff"):
                continue
            counts[h] = counts.get(h, 0) + 1

    # ---- NEW coverage: unused picks are warnings ----
    used_new = []
    for nw in new_words:
        c = counts.get(nw, 0)
        if c < min_new_reps:
            warnings.append(f"NEW pick '{nw}' unused (dropped)")
        else:
            used_new.append(nw)

    # ---- DUE coverage: soft ----
    due_used = []
    for dw in due_words:
        c = counts.get(dw, 0)
        if c < 1:
            warnings.append(f"DUE word '{dw}' not used (will skip rating)")
        else:
            due_used.append(dw)

    # ---- Out-of-pool soft warning ----
    if out_of_pool:
        total_oop = sum(out_of_pool.values())
        warnings.append(
            f"{total_oop} out-of-pool occurrences ({len(out_of_pool)} unique)"
        )

    # ---- Length ----
    char_min = round(target_length * (1 - range_pct / 100))
    char_max = round(target_length * (1 + range_pct / 100))
    if total_chars < char_min * 0.8 or total_chars > char_max * 1.2:
        warnings.append(
            f"length {total_chars} outside {char_min}-{char_max} (±20% tolerance)"
        )

    wishlist = []
    for h, c in sorted(out_of_pool.items(), key=lambda kv: -kv[1]):
        entry = vocab_lookup(h)
        wishlist.append({
            "hanzi": h,
            "count": c,
            "in_freq_list": entry is not None,
            "rank": entry.rank if entry else None,
            "pinyin": entry.pinyin if entry else None,
            "english": entry.english if entry else None,
        })

    stats = {
        "total_chars": total_chars,
        "target_length": target_length,
        "char_min": char_min,
        "char_max": char_max,
        "unique_words": len(counts),
        "new_picks_declared": new_words,
        "new_picks_used": used_new,
        "due_used": due_used,
        "due_covered": len(due_used),
        "out_of_pool_unique": len(out_of_pool),
        "out_of_pool_total": sum(out_of_pool.values()),
    }

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
        "out_of_pool": out_of_pool,
        "wishlist": wishlist,
    }
