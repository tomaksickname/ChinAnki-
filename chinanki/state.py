"""
SRS state for Chinanki.

Phase 1: NEW words are model-picked from un-introduced entries 1..PHASE1_BOUND.
Phase 2: NEW words are fixed, ordered from PHASE1_BOUND+1 upward, toggle/day.

FREE pool:
  Phase 1: entries 1..PHASE1_BOUND
  Phase 2: entries 1..PHASE1_BOUND + free_offset
"""
from __future__ import annotations

import json
from datetime import datetime, date
from typing import Any, Dict, List

from . import config
from .vocab import VocabEntry, load_vocab


def _new_srs(rank: int) -> Dict[str, Any]:
    return {
        "rank": rank,
        "last_reviewed": None,
        "due_date": None,
        "state": "new",
        "step_index": 0,
        "interval_days": None,
        "ease_factor": config.SRS_CONFIG["starting_ease"],
        "review_count": 0,
        "lapses": 0,
        "is_leech": False,
    }


def _seed_words(entries: List[VocabEntry]) -> Dict[str, Any]:
    return {e.hanzi: _new_srs(e.rank) for e in entries}


def new_state() -> Dict[str, Any]:
    vocab = load_vocab()
    seeded = vocab[: config.PHASE1_BOUND]
    now = datetime.now().isoformat()
    return {
        "version": 2,
        "phase1_bound": config.PHASE1_BOUND,
        "created": now,
        "updated": now,
        "today": {},
        "free_offset": config.DEFAULT_FREE_OFFSET,
        "config": dict(config.SRS_CONFIG),
        "words": _seed_words(seeded),
    }


def load_state() -> Dict[str, Any]:
    config.ensure_dirs()
    if not config.SRS_STATE_PATH.exists():
        st = new_state()
        save_state(st)
        return st
    with open(config.SRS_STATE_PATH, "r", encoding="utf-8") as f:
        st = json.load(f)
    _migrate(st)
    return st


def save_state(state: Dict[str, Any]) -> None:
    state["updated"] = datetime.now().isoformat()
    config.ensure_dirs()
    tmp = config.SRS_STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(config.SRS_STATE_PATH)


def _migrate(st: Dict[str, Any]) -> None:
    st.setdefault("phase1_bound", config.PHASE1_BOUND)
    st.setdefault("today", {})
    st.setdefault("free_offset", config.DEFAULT_FREE_OFFSET)
    st.pop("pre_known_count", None)
    st.pop("ceiling_count", None)
    st.pop("rank_ceiling", None)
    # Strip legacy pre_known flags if present
    for srs in st.get("words", {}).values():
        srs.pop("pre_known", None)
    st["version"] = 2


# ==================== DERIVED ====================


def introduced_count(state: Dict[str, Any]) -> int:
    return sum(
        1 for s in state["words"].values()
        if s.get("last_reviewed") is not None
    )


def phase(state: Dict[str, Any]) -> int:
    """1 if any entry in 1..PHASE1_BOUND is un-introduced, else 2."""
    bound = state.get("phase1_bound", config.PHASE1_BOUND)
    vocab = load_vocab()
    for e in vocab[:bound]:
        s = state["words"].get(e.hanzi)
        if s is None or s.get("last_reviewed") is None:
            return 1
    return 2


def free_bound(state: Dict[str, Any]) -> int:
    """How many entries are usable as FREE glue."""
    vocab = load_vocab()
    p1 = state.get("phase1_bound", config.PHASE1_BOUND)
    if phase(state) == 1:
        return min(p1, len(vocab))
    off = state.get("free_offset", 0)
    return min(p1 + off, len(vocab))


def free_pool(state: Dict[str, Any]) -> List[VocabEntry]:
    vocab = load_vocab()
    return vocab[: free_bound(state)]


def new_candidate_pool(state: Dict[str, Any]) -> List[VocabEntry]:
    """
    Entries eligible to be NEW.
    Phase 1: un-introduced entries in 1..PHASE1_BOUND (any order the model wants).
    Phase 2: un-introduced entries in 1..(PHASE1_BOUND + free_offset) — but
             ordered by rank, we take the next `toggle` in order.
    Caller decides how to use.
    """
    vocab = load_vocab()
    p1 = state.get("phase1_bound", config.PHASE1_BOUND)
    if phase(state) == 1:
        limit = p1
    else:
        limit = free_bound(state)
    out = []
    for e in vocab[:limit]:
        s = state["words"].get(e.hanzi)
        if s is None or s.get("last_reviewed") is None:
            out.append(e)
    out.sort(key=lambda e: e.rank)
    return out


def total_entries(state: Dict[str, Any]) -> int:
    return len(load_vocab())


# ==================== TODAY FROZEN BATCH ====================


def _today_iso() -> str:
    return date.today().isoformat()


def freeze_today(state, new_quota, new_words, due_words) -> None:
    state["today"] = {
        "date": _today_iso(),
        "new_quota": new_quota,
        "new_words": list(new_words),
        "due_words": list(due_words),
        "new_introduced": len(new_words),
    }


def get_frozen_today(state: Dict[str, Any]) -> Dict[str, Any]:
    t = state.get("today") or {}
    if t.get("date") != _today_iso():
        return {}
    return t


# ==================== CLI ====================


if __name__ == "__main__":
    config.ensure_dirs()
    st = load_state()
    print(f"State file:        {config.SRS_STATE_PATH}")
    print(f"version:           {st['version']}")
    print(f"phase1_bound:      {st['phase1_bound']}")
    print(f"phase:             {phase(st)}")
    print(f"free_offset:       {st['free_offset']}")
    print(f"free_bound:        {free_bound(st)}")
    print(f"introduced:        {introduced_count(st)}")
    print(f"words tracked:     {len(st['words'])}")
    print(f"today:             {st.get('today')}")
    cands = new_candidate_pool(st)
    print(f"un-introduced candidates: {len(cands)}")
    print("first 3 candidates:")
    for e in cands[:3]:
        print(f"  rank {e.rank}  {e.hanzi}  {e.pinyin}")
