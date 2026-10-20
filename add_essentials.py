#!/usr/bin/env python3
"""
Add essential words to the frequency list.

Reads all data/essentials*.json files. For each essential:
  - MISSING: not in list at all -> add at top
  - DEEP: in list but rank > DEEP_THRESHOLD -> bump to top
  - FINE: in list at good rank -> leave alone
  - SKIPPED: conflicts with existing (different pinyin/meaning) -> skip

With --apply: prepends all (missing + bumped) at ranks 1..N, pushes old down.
Backs up the original file first.
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FREQ = ROOT / "data" / "frequency_list_v4_final.json"
ESSENTIALS_GLOB = str(ROOT / "data" / "essentials*.json")

DEEP_THRESHOLD = 1000

# Hanzi that conflict with existing list entries (different reading/meaning).
SKIP_HANZI = {"还", "带", "只"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually modify the freq list (default: dry-run)")
    args = ap.parse_args()

    freq = load_json(FREQ)
    freq_by_hanzi = {e["hanzi"]: e for e in freq}

    # Load all essentials files, dedupe by hanzi
    ess_files = sorted(glob.glob(ESSENTIALS_GLOB))
    essentials = []
    seen_ess = set()
    for path in ess_files:
        for e in load_json(path):
            if e["hanzi"] in seen_ess:
                continue
            seen_ess.add(e["hanzi"])
            essentials.append(e)
    print(f"Loaded {len(essentials)} essentials from {len(ess_files)} file(s):")
    for p in ess_files:
        print(f"  {Path(p).name}")
    print()

    missing, deep, fine, skipped = [], [], [], []
    for ess in essentials:
        h = ess["hanzi"]
        if h in SKIP_HANZI:
            skipped.append(ess)
            continue
        existing = freq_by_hanzi.get(h)
        if existing is None:
            missing.append(ess)
        elif existing["rank"] > DEEP_THRESHOLD:
            deep.append((ess, existing["rank"]))
        else:
            fine.append((ess, existing["rank"]))

    print(f"Essentials total: {len(essentials)}")
    print(f"  MISSING (add at top):                {len(missing)}")
    print(f"  DEEP (rank > {DEEP_THRESHOLD}, bump):       {len(deep)}")
    print(f"  FINE (rank <= {DEEP_THRESHOLD}, untouched): {len(fine)}")
    print()

    if skipped:
        print(f"SKIPPED (conflict with existing):  {len(skipped)}")
        for e in skipped:
            print(f"  {e['hanzi']:6} {e['pinyin']:12} {e['english']}")
        print()

    if missing:
        print(f"=== MISSING ({len(missing)}) ===")
        for e in missing:
            print(f"  {e['hanzi']:6} {e['pinyin']:12} {e['english']}")
        print()

    if deep:
        print(f"=== DEEP (will be bumped to top) ===")
        for e, r in deep:
            print(f"  {e['hanzi']:6} rank was {r}  {e['english']}")
        print()

    to_add = missing + [e for e, _ in deep]
    n_add = len(to_add)

    if n_add == 0:
        print("Nothing to add.")
        return

    old_ranks_pushed_out = []
    for e in freq:
        new_rank = e["rank"] + n_add
        if e["rank"] <= 1000 and new_rank > 1000:
            old_ranks_pushed_out.append((e["hanzi"], e["rank"], new_rank))

    print(f"Total to add at top: {n_add}")
    print()
    print(f"=== Entries pushed out of top 1000 ({len(old_ranks_pushed_out)}) ===")
    for h, old, new in old_ranks_pushed_out[-30:]:
        print(f"  {h:6} rank {old} -> {new}")

    if not args.apply:
        print()
        print("DRY RUN. Re-run with --apply to write changes.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = FREQ.with_name(f"frequency_list_v4_final.backup_{stamp}.json")
    shutil.copy(FREQ, backup)
    print(f"\nBacked up original to {backup.name}")

    deep_hanzi = {e["hanzi"] for e, _ in deep}
    freq_minus = [e for e in freq if e["hanzi"] not in deep_hanzi]

    new_list = []
    for i, ess in enumerate(to_add, start=1):
        entry = {
            "rank": i,
            "hanzi": ess["hanzi"],
            "pinyin": ess["pinyin"],
            "english": ess["english"],
            "traditional": ess.get("traditional", ess["hanzi"]),
            "pos": ess.get("pos", ""),
            "zipf": 0.0,
            "cd_n": 0,
            "word_length": len(ess["hanzi"]),
            "_essential": True,
            "_category": ess.get("category", ""),
        }
        new_list.append(entry)

    for j, e in enumerate(freq_minus, start=n_add + 1):
        e["rank"] = j
        new_list.append(e)

    save_json(FREQ, new_list)
    print(f"Wrote {len(new_list)} entries to {FREQ.name}")
    print(f"  Added {n_add} essentials at top")
    print(f"  Old entries pushed down by {n_add}")


if __name__ == "__main__":
    main()
