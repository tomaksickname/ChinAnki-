"""
Local HTTP server for Chinanki.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
import urllib.parse
from datetime import datetime, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from . import state as state_mod
from .srs import get_today_cards, stats as srs_stats
from .tts import synth_word, synth_story, synth_sentence, story_full_text
from .prompts import SYSTEM_TOPICS, build_topic_prompt
from .generate_story import call_deepseek, parse_json_loose, generate_once, save_story


def _story_meta(rec: Dict[str, Any]) -> Dict[str, Any]:
    gen = rec.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(gen)
        days_ago = (date.today() - dt.date()).days
    except Exception:
        days_ago = None
    return {
        "id": rec.get("id"),
        "date": gen,
        "days_ago": days_ago,
        "title_english": rec.get("title_english", "") or rec.get("topic", ""),
        "title_hanzi": rec.get("title_hanzi", ""),
        "title_pinyin": rec.get("title_pinyin", ""),
        "topic": rec.get("topic", ""),
        "new_words": rec.get("new_words", []),
        "due_words": rec.get("due_words", []),
        "target_minutes": rec.get("target_minutes", 0),
        "char_count": _char_count(rec),
    }


def _char_count(rec: Dict[str, Any]) -> int:
    n = 0
    for s in rec.get("sentences", []):
        for w in s.get("words", []):
            if w.get("punct"):
                continue
            n += len(w.get("hanzi", ""))
    return n


def list_stories(limit: int = 20) -> List[Dict[str, Any]]:
    files = sorted(config.STORIES_DIR.glob("*.json"), reverse=True)
    out = []
    for p in files[:limit]:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            out.append(_story_meta(rec))
        except Exception:
            continue
    return out


def load_story(story_id: str) -> Optional[Dict[str, Any]]:
    p = config.STORIES_DIR / f"{story_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_story_record(story_id: str, rec: Dict[str, Any]) -> None:
    p = config.STORIES_DIR / f"{story_id}.json"
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def suggest_minutes(rec: Dict[str, Any]) -> int:
    target_chars = _char_count(rec)
    best = None
    best_diff = None
    for p in config.STORIES_DIR.glob("*.json"):
        try:
            other = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = other.get("target_minutes")
        if not m:
            continue
        oc = _char_count(other)
        if oc <= 0:
            continue
        diff = abs(oc - target_chars)
        if best_diff is None or diff < best_diff:
            best = (oc, m)
            best_diff = diff

    if best is not None:
        oc, m = best
        scaled = max(1, round(m * target_chars / oc))
        return scaled

    if target_chars <= 0:
        return 4
    return max(1, round(target_chars / 55))


def get_state_summary() -> Dict[str, Any]:
    st = state_mod.load_state()
    ph = state_mod.phase(st)
    frozen = state_mod.get_frozen_today(st)
    return {
        "phase": ph,
        "free_bound": state_mod.free_bound(st),
        "introduced": state_mod.introduced_count(st),
        "today": frozen,
        "stats": srs_stats(st, toggle=config.DEFAULT_NEW_PER_DAY),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Chinanki/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path, content_type: Optional[str] = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, f"Not found: {path.name}")
            return
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(path))
            content_type = content_type or "application/octet-stream"
        data = path.read_bytes()
        self.send_bytes(data, content_type)

    def read_body_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _audio_ctype(self, p: Path) -> str:
        return "audio/mpeg" if p.suffix == ".mp3" else "audio/mp4"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                return self.send_file(config.APP_DIR / "index.html")
            if path.startswith("/app/"):
                rel = path[len("/app/"):]
                return self.send_file(config.APP_DIR / rel)
            if path == "/api/state":
                return self.send_json(get_state_summary())
            if path == "/api/stories":
                return self.send_json({"stories": list_stories(20)})
            if path.startswith("/api/story/"):
                sid = path[len("/api/story/"):]
                if sid.endswith("/suggest_minutes"):
                    sid = sid[:-len("/suggest_minutes")]
                    rec = load_story(sid)
                    if rec is None:
                        return self.send_json({"error": "not found"}, status=404)
                    return self.send_json({"minutes": suggest_minutes(rec)})
                rec = load_story(sid)
                if rec is None:
                    return self.send_json({"error": "not found"}, status=404)
                return self.send_json(rec)
            if path == "/api/topics":
                hint = qs.get("hint", [""])[0]
                return self.handle_topics(hint)
            if path.startswith("/api/audio/word/"):
                hanzi = urllib.parse.unquote(path[len("/api/audio/word/"):])
                return self.handle_audio_word(hanzi)
            if path.startswith("/api/audio/sentence/"):
                rest = path[len("/api/audio/sentence/"):]
                return self.handle_audio_sentence(rest)
            if path.startswith("/api/audio/story/"):
                sid = path[len("/api/audio/story/"):]
                return self.handle_audio_story(sid)
            self.send_error(404, "Unknown path")
        except Exception as e:
            tb = traceback.format_exc()
            sys.stderr.write(tb)
            self.send_json({"error": str(e), "traceback": tb}, status=500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/generate":
                return self.handle_generate()
            if path.startswith("/api/story/") and path.endswith("/minutes"):
                sid = path[len("/api/story/"):-len("/minutes")]
                return self.handle_set_minutes(sid)
            self.send_error(404, "Unknown path")
        except Exception as e:
            tb = traceback.format_exc()
            sys.stderr.write(tb)
            self.send_json({"error": str(e), "traceback": tb}, status=500)

    def handle_topics(self, hint: str) -> None:
        st = state_mod.load_state()
        ph = state_mod.phase(st)
        today = get_today_cards(st, config.DEFAULT_NEW_PER_DAY)
        free_pool = state_mod.free_pool(st)
        user_prompt = build_topic_prompt(
            today["new"], today["due"], free_pool,
            count=config.TOPIC_CHIP_COUNT, user_hint=hint, phase=ph,
        )
        try:
            raw = call_deepseek(SYSTEM_TOPICS, user_prompt, max_tokens=800)
            obj = parse_json_loose(raw)
            topics = obj.get("topics", [])
            return self.send_json({"topics": topics})
        except Exception as e:
            return self.send_json({"topics": [], "error": str(e)}, status=500)

    def handle_generate(self) -> None:
        body = self.read_body_json()
        topic = body.get("topic", "")
        length = int(body.get("length", config.DEFAULT_LENGTH))
        range_pct = int(body.get("range", config.DEFAULT_RANGE_PCT))
        new_count = int(body.get("new", config.DEFAULT_NEW_PER_DAY))

        st = state_mod.load_state()
        first_today = not bool(state_mod.get_frozen_today(st))

        attempt_lengths = [
            length,
            min(500, int(length * 1.15)),
            min(500, int(length * 1.30)),
        ]
        MAX_TOTAL_ATTEMPTS = 15
        last_errors: List[str] = []
        story = None
        new_picks: List[str] = []
        due_hanzi: List[str] = []
        validation_result: Dict[str, Any] = {}
        used_length = length
        attempts_log: List[Dict[str, Any]] = []

        attempt_num = 0
        while attempt_num < MAX_TOTAL_ATTEMPTS:
            attempt_num += 1
            attempt_len = attempt_lengths[min((attempt_num - 1) % 3, 2)]
            story, errors, new_picks, due_hanzi, validation_result = generate_once(
                st, user_topic=topic, length=attempt_len,
                range_pct=range_pct, toggle=new_count, verbose=False,
            )
            attempts_log.append({
                "attempt": attempt_num,
                "length": attempt_len,
                "ok": story is not None,
                "errors": errors[:8],
            })
            if story is not None:
                used_length = attempt_len
                break
            last_errors = errors

        if story is None:
            return self.send_json({
                "ok": False,
                "attempts": attempts_log,
                "last_errors": last_errors,
            }, status=200)

        rec = save_story(
            st, story, new_picks, due_hanzi,
            toggle=new_count, user_topic=topic,
            target_length=used_length, range_pct=range_pct,
            first_today=first_today,
            validation_result=validation_result,
        )
        rec["target_minutes"] = suggest_minutes(rec)
        save_story_record(rec["id"], rec)
        return self.send_json({"ok": True, "story": rec, "attempts": attempts_log})

    def handle_set_minutes(self, story_id: str) -> None:
        body = self.read_body_json()
        try:
            minutes = int(body.get("minutes", 0))
        except (ValueError, TypeError):
            minutes = 0
        rec = load_story(story_id)
        if rec is None:
            return self.send_json({"error": "not found"}, status=404)
        rec["target_minutes"] = minutes
        save_story_record(story_id, rec)
        return self.send_json({"ok": True, "target_minutes": minutes})

    def handle_audio_word(self, hanzi: str) -> None:
        p = synth_word(hanzi)
        if p is None or not p.exists():
            return self.send_error(404, f"No audio for {hanzi}")
        return self.send_file(p, self._audio_ctype(p))

    def handle_audio_story(self, story_id: str) -> None:
        rec = load_story(story_id)
        if rec is None:
            return self.send_error(404, "Story not found")
        text = story_full_text(rec)
        p = synth_story(story_id, text)
        if p is None or not p.exists():
            return self.send_error(500, "TTS failed")
        return self.send_file(p, self._audio_ctype(p))

    def handle_audio_sentence(self, rest: str) -> None:
        if "/" not in rest:
            return self.send_error(400, "Bad sentence path")
        story_id, s_idx_str = rest.rsplit("/", 1)
        try:
            s_idx = int(s_idx_str)
        except ValueError:
            return self.send_error(400, "Bad sentence index")
        rec = load_story(story_id)
        if rec is None:
            return self.send_error(404, "Story not found")
        sentences = rec.get("sentences", [])
        if s_idx < 0 or s_idx >= len(sentences):
            return self.send_error(404, "Sentence index out of range")
        text = sentences[s_idx].get("hanzi", "").strip()
        if not text:
            return self.send_error(404, "Empty sentence")
        p = synth_sentence(story_id, s_idx, text)
        if p is None or not p.exists():
            return self.send_error(500, "TTS failed")
        return self.send_file(p, self._audio_ctype(p))


def main() -> int:
    config.ensure_dirs()
    port = config.PORT
    host = config.HOST
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Chinanki serving at http://{host}:{port}/")
    print(f"  stories: {config.STORIES_DIR}")
    print(f"  audio:   {config.AUDIO_DIR}")
    print(f"  TTS:     {config.TTS_BACKEND}")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
