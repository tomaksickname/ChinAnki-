"""
TTS for Chinanki.

Backends:
  - macsay (fallback): macOS `say` -> afconvert -> m4a
  - azure:  Azure Speech REST API -> mp3 (better Mandarin)

Cache layout:
  audio/words/<hanzi>.mp3
  audio/stories/<story_id>.mp3              (master, full story)
  audio/stories/<story_id>/s<idx>.mp3       (per-sentence)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests

from . import config


# ==================== BACKENDS ====================


class TTSBackend:
    name = "base"
    ext = ".mp3"

    def synth_to_file(self, text: str, out_path: Path) -> None:
        raise NotImplementedError


class MacSayTTS(TTSBackend):
    name = "macsay"
    ext = ".m4a"

    def __init__(self, voice: str = "Tingting"):
        self.voice = voice

    def synth_to_file(self, text: str, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        aiff_path = out_path.with_suffix(".aiff")
        m4a_path = out_path.with_suffix(".m4a")

        say_bin = "/usr/bin/say"
        if not Path(say_bin).exists():
            raise RuntimeError(f"{say_bin} not found (macOS only)")
        result = subprocess.run(
            [say_bin, "-v", self.voice, "-o", str(aiff_path), text],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"say failed: {result.stderr}")

        afconvert_bin = "/usr/bin/afconvert"
        if not Path(afconvert_bin).exists():
            aiff_path.replace(out_path)
            return
        result = subprocess.run(
            [afconvert_bin, "-f", "m4af", "-d", "aac", "-b", "64000",
             str(aiff_path), str(m4a_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"afconvert failed: {result.stderr}")
        try:
            aiff_path.unlink()
        except FileNotFoundError:
            pass


class AzureTTS(TTSBackend):
    name = "azure"
    ext = ".mp3"

    def __init__(self, key: str, region: str, voice: str):
        if not key or not region:
            raise RuntimeError("Azure TTS requires AZURE_TTS_KEY and AZURE_TTS_REGION")
        self.key = key
        self.region = region
        self.voice = voice

    def _endpoint(self) -> str:
        return f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"

    def synth_to_file(self, text: str, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        safe = (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;"))
        ssml = (
            "<speak version='1.0' xml:lang='zh-CN'>"
            f"<voice name='{self.voice}'>{safe}</voice>"
            "</speak>"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "Chinanki",
        }
        r = requests.post(self._endpoint(), headers=headers,
                          data=ssml.encode("utf-8"), timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Azure TTS HTTP {r.status_code}: {r.text[:300]}")
        out_path.write_bytes(r.content)


def get_tts() -> TTSBackend:
    backend = config.TTS_BACKEND.lower()
    if backend == "azure":
        return AzureTTS(config.AZURE_TTS_KEY, config.AZURE_TTS_REGION,
                        config.AZURE_TTS_VOICE)
    if backend == "macsay":
        return MacSayTTS(voice=config.MACSAY_VOICE)
    raise ValueError(f"Unknown TTS_BACKEND: {backend}")


# ==================== PATHS ====================


def _word_path(hanzi: str) -> Path:
    safe = hanzi.replace("/", "_")
    backend = get_tts()
    return config.AUDIO_WORDS_DIR / f"{safe}{backend.ext}"


def _story_master_path(story_id: str) -> Path:
    backend = get_tts()
    return config.AUDIO_STORIES_DIR / f"{story_id}{backend.ext}"


def _story_sentence_dir(story_id: str) -> Path:
    return config.AUDIO_STORIES_DIR / story_id


def _sentence_path(story_id: str, s_idx: int) -> Path:
    backend = get_tts()
    return _story_sentence_dir(story_id) / f"s{s_idx}{backend.ext}"


# ==================== SYNTH ====================


def synth_word(hanzi: str, force: bool = False) -> Optional[Path]:
    if not hanzi or not hanzi.strip():
        return None
    out = _word_path(hanzi)
    if out.exists() and not force:
        return out
    backend = get_tts()
    try:
        backend.synth_to_file(hanzi, out)
    except Exception as e:
        print(f"  [tts] failed for '{hanzi}': {e}")
        return None
    return out if out.exists() else None


def synth_story(story_id: str, full_text: str, force: bool = False) -> Optional[Path]:
    out = _story_master_path(story_id)
    if out.exists() and not force:
        return out
    backend = get_tts()
    try:
        backend.synth_to_file(full_text, out)
    except Exception as e:
        print(f"  [tts] failed for story {story_id}: {e}")
        return None
    return out if out.exists() else None


def synth_sentence(story_id: str, s_idx: int, text: str,
                   force: bool = False) -> Optional[Path]:
    out = _sentence_path(story_id, s_idx)
    if out.exists() and not force:
        return out
    backend = get_tts()
    try:
        backend.synth_to_file(text, out)
    except Exception as e:
        print(f"  [tts] failed for story {story_id} s{s_idx}: {e}")
        return None
    return out if out.exists() else None


def synth_story_sentences(story_id: str, story_record: dict,
                          force: bool = False) -> int:
    """Generate all per-sentence audio for a story. Returns count OK."""
    ok = 0
    for i, sent in enumerate(story_record.get("sentences", [])):
        text = sent.get("hanzi", "").strip()
        if not text:
            continue
        p = synth_sentence(story_id, i, text, force=force)
        if p:
            ok += 1
    return ok


def story_full_text(story_record: dict) -> str:
    return "".join(s.get("hanzi", "") for s in story_record.get("sentences", []))


# ==================== CLI ====================


def _collect_today_words() -> list:
    from .state import load_state, get_frozen_today
    st = load_state()
    frozen = get_frozen_today(st)
    if not frozen:
        return []
    seen = []
    for h in frozen.get("new_words", []) + frozen.get("due_words", []):
        if h not in seen:
            seen.append(h)
    return seen


def _collect_story_words(story_id: str) -> list:
    import json
    p = config.STORIES_DIR / f"{story_id}.json"
    if not p.exists():
        return []
    rec = json.loads(p.read_text(encoding="utf-8"))
    seen = []
    for s in rec.get("sentences", []):
        for w in s.get("words", []):
            if w.get("punct"):
                continue
            h = w.get("hanzi")
            if h and h not in seen:
                seen.append(h)
    return seen


def main() -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Chinanki TTS")
    ap.add_argument("word", nargs="?", help="Single word to synthesize")
    ap.add_argument("--warm", action="store_true",
                    help="Pre-generate audio for today's NEW + DUE batch")
    ap.add_argument("--warm-story", metavar="STORY_ID",
                    help="Pre-generate audio for every word in a saved story")
    ap.add_argument("--warm-all", action="store_true",
                    help="Pre-generate audio for every word in the current pool")
    ap.add_argument("--story", metavar="STORY_ID",
                    help="Generate master story audio")
    ap.add_argument("--sentences", metavar="STORY_ID",
                    help="Generate per-sentence audio for a story")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()

    if args.word:
        p = synth_word(args.word, force=args.force)
        if p:
            print(f"OK: {p}")
            return 0
        return 1

    if args.warm:
        words = _collect_today_words()
        if not words:
            print("No frozen batch for today. Run a generation first.")
            return 1
        print(f"Warming audio for {len(words)} words...")
        ok = 0
        for h in words:
            p = synth_word(h, force=args.force)
            if p:
                ok += 1
                print(f"  {h}  ->  {p.name}")
            else:
                print(f"  {h}  FAILED")
        print(f"Done: {ok}/{len(words)}")
        return 0

    if args.warm_story:
        words = _collect_story_words(args.warm_story)
        if not words:
            print(f"No words found for story {args.warm_story}")
            return 1
        print(f"Warming audio for {len(words)} words in story {args.warm_story}...")
        ok = 0
        for h in words:
            p = synth_word(h, force=args.force)
            if p:
                ok += 1
            else:
                print(f"  {h}  FAILED")
        print(f"Done: {ok}/{len(words)}")
        return 0

    if args.warm_all:
        from .state import load_state, free_pool
        st = load_state()
        pool = free_pool(st)
        print(f"Warming audio for {len(pool)} words (this will take a while)...")
        ok = 0
        for e in pool:
            p = synth_word(e.hanzi, force=args.force)
            if p:
                ok += 1
                if ok % 50 == 0:
                    print(f"  {ok}/{len(pool)}...")
        print(f"Done: {ok}/{len(pool)}")
        return 0

    if args.story:
        p = config.STORIES_DIR / f"{args.story}.json"
        if not p.exists():
            print(f"Story not found: {p}")
            return 1
        rec = json.loads(p.read_text(encoding="utf-8"))
        text = story_full_text(rec)
        out = synth_story(args.story, text, force=args.force)
        if out:
            print(f"OK: {out}")
            return 0
        return 1

    if args.sentences:
        p = config.STORIES_DIR / f"{args.sentences}.json"
        if not p.exists():
            print(f"Story not found: {p}")
            return 1
        rec = json.loads(p.read_text(encoding="utf-8"))
        n_sent = len(rec.get("sentences", []))
        print(f"Generating {n_sent} sentence files for {args.sentences}...")
        ok = synth_story_sentences(args.sentences, rec, force=args.force)
        print(f"Done: {ok}/{n_sent}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
