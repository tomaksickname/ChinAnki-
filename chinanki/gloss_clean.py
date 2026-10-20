"""
Clean up glosses for display in the reader.
"""
from __future__ import annotations

import re


_PAREN = re.compile(r"\s*\([^)]*\)")
_ELLIPSIS = re.compile(r"\s*(\.\.\.|…)\s*$")
_SPACES = re.compile(r"\s+")


def _strip_truncated_tail(part: str) -> str:
    tokens = part.split()
    if not tokens:
        return part
    last = tokens[-1].strip(".,;:!?")
    if len(last) <= 2:
        tokens = tokens[:-1]
    return " ".join(tokens).strip()


def clean_gloss(raw: str, max_glosses: int = 2) -> str:
    if not raw:
        return ""

    was_truncated = bool(_ELLIPSIS.search(raw.strip()))

    s = raw.strip()
    s = _PAREN.sub("", s)
    s = _ELLIPSIS.sub("", s)

    parts = [p.strip() for p in s.split(";") if p.strip()]

    if was_truncated and parts:
        parts[-1] = _strip_truncated_tail(parts[-1])

    parts = [p for p in parts if p]

    kept = parts[:max_glosses]
    s = "; ".join(kept) if kept else ""
    s = s.strip(" ;,.")
    s = _SPACES.sub(" ", s)
    return s


def short_gloss(raw: str) -> str:
    return clean_gloss(raw, max_glosses=1)


if __name__ == "__main__":
    samples = [
        "of; ~'s (possessive particle)",
        "to be (followed by substantives only); c...",
        "(after completing a game of chess) to replay th...",
        "(third-person singular) (since the early 20th c...",
        "old friend; menstruation",
        "to hold; to grasp; to hold a baby in position to help it urinate o...; handlebar",
        "happy; joyful",
        "to go",
    ]
    for s in samples:
        print(f"RAW:   {s}")
        print(f"CLEAN: {clean_gloss(s)}")
        print()
