"""
Load frequency_list_v4_final.json. Lookup by hanzi or rank.
No SRS logic here - just the static list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

from . import config


@dataclass(frozen=True)
class VocabEntry:
    rank: int
    hanzi: str
    pinyin: str
    english: str
    traditional: str
    pos: str
    zipf: float
    cd_n: int
    word_length: int


@lru_cache(maxsize=1)
def load_vocab() -> List[VocabEntry]:
    """Load and cache the frequency list."""
    with open(config.FREQ_LIST_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    entries = []
    seen_hanzi = set()
    for row in raw:
        h = row["hanzi"]
        if h in seen_hanzi:
            raise ValueError(f"Duplicate hanzi in freq list: {h} (rank {row['rank']})")
        seen_hanzi.add(h)
        entries.append(VocabEntry(
            rank=int(row["rank"]),
            hanzi=h,
            pinyin=row.get("pinyin", ""),
            english=row.get("english", ""),
            traditional=row.get("traditional", h),
            pos=row.get("pos", ""),
            zipf=float(row.get("zipf", 0.0)),
            cd_n=int(row.get("cd_n", 0)),
            word_length=int(row.get("word_length", len(h))),
        ))

    entries.sort(key=lambda e: e.rank)
    return entries


@lru_cache(maxsize=1)
def by_hanzi() -> Dict[str, VocabEntry]:
    return {e.hanzi: e for e in load_vocab()}


@lru_cache(maxsize=1)
def by_rank() -> Dict[int, VocabEntry]:
    return {e.rank: e for e in load_vocab()}


def lookup(hanzi: str) -> Optional[VocabEntry]:
    return by_hanzi().get(hanzi)


def entry_at_rank(rank: int) -> Optional[VocabEntry]:
    return by_rank().get(rank)


def in_list(hanzi: str) -> bool:
    return hanzi in by_hanzi()


def rank_of(hanzi: str) -> Optional[int]:
    e = by_hanzi().get(hanzi)
    return e.rank if e else None


# ---------- CLI ----------

if __name__ == "__main__":
    v = load_vocab()
    print(f"Loaded {len(v)} entries from {config.FREQ_LIST_PATH}")
    print()
    print("First 5:")
    for e in v[:5]:
        print(f"  {e.rank:>4}  {e.hanzi:<4}  {e.pinyin:<12}  {e.english[:40]}")
    print()
    print("Last 3:")
    for e in v[-3:]:
        print(f"  {e.rank:>4}  {e.hanzi:<4}  {e.pinyin:<12}  {e.english[:40]}")
    print()
    print(f"Rank 500: {entry_at_rank(500)}")
    print(f"lookup('着急'): {lookup('着急')}")
    print(f"lookup('zzz'): {lookup('zzz')}")
