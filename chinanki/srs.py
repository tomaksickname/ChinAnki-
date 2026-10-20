"""
SRS engine for Chinanki. See state.py for the model.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional

from . import config
from .vocab import VocabEntry, load_vocab, lookup
from . import state as state_mod


def _is_new(srs: Dict[str, Any]) -> bool:
    return srs.get("last_reviewed") is None


def sample_new_candidates(st: Dict[str, Any], n: Optional[int] = None) -> List[VocabEntry]:
    """
    Return a small daily sample of un-introduced words to offer as NEW
    candidates. Sampling is seeded by today's date so the pool is stable
    across multiple generations in one day.
    """
    if n is None:
        n = config.NEW_CANDIDATE_POOL

    vocab = load_vocab()
    ceiling = st.get("phase1_bound", config.PHASE1_BOUND)
    search_bound = min(config.NEW_CANDIDATE_SEARCH_BOUND, ceiling)
    pool_top = vocab[:search_bound]

    un_introduced = [
        e for e in pool_top
        if _is_new(st["words"].get(e.hanzi, {}))
    ]

    # If the top search_bound is nearly exhausted, extend upward.
    if len(un_introduced) < n:
        extra = [
            e for e in vocab[search_bound:ceiling]
            if _is_new(st["words"].get(e.hanzi, {}))
        ]
        un_introduced.extend(extra)

    if not un_introduced:
        return []

    # Deterministic per-day sampling
    from datetime import date
    rng = random.Random(date.today().toordinal())
    n = min(n, len(un_introduced))
    sample = rng.sample(un_introduced, n)
    sample.sort(key=lambda e: e.rank)
    return sample


def get_new_cards(st, toggle, count=None) -> List[VocabEntry]:
    """
    Return the NEW batch for today.
    - If today is frozen, return the frozen list.
    - Otherwise, return the sampled candidate pool (model will pick from it).
    """
    frozen = state_mod.get_frozen_today(st)
    if frozen:
        return [lookup(h) for h in frozen.get("new_words", []) if lookup(h)]

    return sample_new_candidates(st, n=config.NEW_CANDIDATE_POOL)


def get_due_reviews(st, toggle, now=None) -> List[VocabEntry]:
    frozen = state_mod.get_frozen_today(st)
    if frozen:
        return [lookup(h) for h in frozen.get("due_words", []) if lookup(h)]
    if now is None:
        now = datetime.now()
    end_of_today = datetime.combine(now.date(), dtime.max)
    p = state_mod.free_pool(st)
    cfg = st.get("config", config.SRS_CONFIG)
    leech_action = cfg.get("leech_action", "suspend")
    due = []
    for e in p:
        srs = st["words"].get(e.hanzi)
        if srs is None:
            continue
        if _is_new(srs):
            continue
        if srs.get("is_leech") and leech_action == "suspend":
            continue
        if srs.get("state") == "learning":
            due.append(e)
            continue
        dd = srs.get("due_date")
        if not dd:
            continue
        try:
            d = datetime.fromisoformat(dd)
        except (ValueError, TypeError):
            continue
        if d <= end_of_today:
            due.append(e)
    due.sort(key=lambda e: st["words"][e.hanzi].get("due_date") or "")
    return due


def get_free_glue(st) -> List[VocabEntry]:
    """Top N highest-frequency words to send as FREE glue."""
    vocab = load_vocab()
    ceiling = st.get("phase1_bound", config.PHASE1_BOUND)
    n = min(config.FREE_GLUE_SIZE, ceiling)
    return vocab[:n]


def get_today_cards(st, toggle, now=None) -> Dict[str, List[VocabEntry]]:
    """
    Returns {new, due, free}.
    - new: candidate pool for the model to pick from
    - due: words to weave in
    - free: glue vocabulary
    """
    new = get_new_cards(st, toggle)
    new_set = {e.hanzi for e in new}
    due = [e for e in get_due_reviews(st, toggle, now) if e.hanzi not in new_set]
    due_set = {e.hanzi for e in due}
    glue = get_free_glue(st)
    free = [e for e in glue if e.hanzi not in new_set and e.hanzi not in due_set]
    return {"new": new, "due": due, "free": free}


def rate_card(st, hanzi, rating, now=None):
    if rating not in ("again", "hard", "good", "easy"):
        raise ValueError(f"Invalid rating: {rating}")
    if now is None:
        now = datetime.now()
    srs = st["words"].get(hanzi)
    if srs is None:
        raise KeyError(f"Unknown hanzi: {hanzi}")
    srs["last_reviewed"] = now.isoformat()
    srs["review_count"] = srs.get("review_count", 0) + 1
    cur = srs.get("state", "new")
    if cur in ("new", "learning"):
        _update_learning(st, srs, rating, now)
    else:
        _update_review(st, srs, rating, now)
    _check_leech(st, srs)
    return srs


def _update_learning(st, srs, rating, now):
    cfg = st.get("config", config.SRS_CONFIG)
    steps = cfg["learning_steps_minutes"]
    idx = srs.get("step_index", 0)
    if rating == "again":
        srs["state"] = "learning"
        srs["step_index"] = 0
        srs["lapses"] = srs.get("lapses", 0) + 1
        srs["due_date"] = (now + timedelta(minutes=steps[0])).isoformat()
    elif rating == "hard":
        srs["state"] = "learning"
        srs["step_index"] = min(idx, len(steps) - 1)
        srs["due_date"] = (now + timedelta(minutes=steps[srs["step_index"]])).isoformat()
    elif rating == "good":
        nxt = idx + 1
        if nxt < len(steps):
            srs["state"] = "learning"
            srs["step_index"] = nxt
            srs["due_date"] = (now + timedelta(minutes=steps[nxt])).isoformat()
        else:
            _graduate(st, srs, now, easy=False)
    elif rating == "easy":
        srs["ease_factor"] = min(cfg["max_ease_factor"],
                                 srs.get("ease_factor", cfg["starting_ease"]) + 0.15)
        _graduate(st, srs, now, easy=True)


def _graduate(st, srs, now, easy=False):
    cfg = st.get("config", config.SRS_CONFIG)
    interval = cfg["easy_interval_days"] if easy else cfg["graduating_interval_days"]
    srs["state"] = "review"
    srs["step_index"] = 0
    srs["interval_days"] = interval
    srs.setdefault("ease_factor", cfg["starting_ease"])
    srs["due_date"] = (now + timedelta(days=interval)).isoformat()


def _update_review(st, srs, rating, now):
    cfg = st.get("config", config.SRS_CONFIG)
    old = srs.get("interval_days", 1) or 1
    ease = srs.get("ease_factor", cfg["starting_ease"])
    mod = cfg.get("interval_modifier", 1.0)
    if rating == "again":
        srs["state"] = "learning"
        srs["step_index"] = 0
        srs["lapses"] = srs.get("lapses", 0) + 1
        srs["ease_factor"] = max(cfg["min_ease_factor"], ease - 0.2)
        srs["interval_days"] = 1
        srs["due_date"] = (now + timedelta(minutes=cfg["learning_steps_minutes"][0])).isoformat()
    elif rating == "hard":
        srs["ease_factor"] = max(cfg["min_ease_factor"], ease - 0.15)
        ni = max(1.0, old * cfg["hard_interval_multiplier"] * mod)
        srs["interval_days"] = ni
        srs["due_date"] = (now + timedelta(days=ni)).isoformat()
    elif rating == "good":
        ni = max(1.0, old * ease * mod)
        srs["interval_days"] = ni
        srs["due_date"] = (now + timedelta(days=ni)).isoformat()
    elif rating == "easy":
        srs["ease_factor"] = min(cfg["max_ease_factor"], ease + 0.15)
        ni = max(1.0, old * ease * cfg["easy_bonus"] * mod)
        srs["interval_days"] = ni
        srs["due_date"] = (now + timedelta(days=ni)).isoformat()


def _check_leech(st, srs):
    cfg = st.get("config", config.SRS_CONFIG)
    if srs.get("lapses", 0) >= cfg["leech_threshold"] and not srs.get("is_leech"):
        srs["is_leech"] = True


def stats(st, toggle=0):
    p = state_mod.free_pool(st)
    total = len(p)
    new_remaining = sum(
        1 for e in p if _is_new(st["words"][e.hanzi])
    )
    learning = sum(
        1 for e in p
        if not _is_new(st["words"][e.hanzi])
        and st["words"][e.hanzi].get("state") == "learning"
    )
    review = total - new_remaining - learning
    leeches = sum(1 for e in p if st["words"][e.hanzi].get("is_leech"))
    return {
        "phase": state_mod.phase(st),
        "free_bound": state_mod.free_bound(st),
        "pool_size": total,
        "new_remaining": new_remaining,
        "learning": learning,
        "review": review,
        "leeches": leeches,
    }


if __name__ == "__main__":
    from .state import load_state
    st = load_state()
    print("=== Stats ===")
    for k, v in stats(st, toggle=10).items():
        print(f"  {k}: {v}")
    print()
    today = get_today_cards(st, toggle=10)
    print(f"NEW candidates: {len(today['new'])}")
    for e in today["new"][:5]:
        print(f"  rank {e.rank}  {e.hanzi}  {e.pinyin}")
    print(f"DUE:  {len(today['due'])}")
    print(f"FREE (glue): {len(today['free'])}")
