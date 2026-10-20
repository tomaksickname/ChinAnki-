"""Prompt templates for DeepSeek."""
from __future__ import annotations

from typing import List

from .vocab import VocabEntry
from .gloss_clean import clean_gloss


SYSTEM_STORY = """You are a Mandarin graded-reader author writing for an adult \
learner at roughly HSK 4-5 / CEFR B1, but with a HARD CONSTRAINT on vocabulary. \
You write short, natural, vivid pieces with concrete scenes, small tensions, and \
real endings. Never textbook dialogue. Never stiff. Simplified characters only.

VOCABULARY RULE — this is the most important rule:
You may ONLY use Chinese words that appear in the vocabulary lists provided in \
the user message. This is an absolute constraint. If you want to express \
something and the word you need is NOT in the lists, you MUST rewrite the \
sentence to avoid it. Do NOT invent words. Do NOT use fragments of words. Do \
NOT guess whether a word is common enough to be allowed — if it is not in the \
lists, it is forbidden. Prefer simpler HSK 1-3 level vocabulary when several \
options exist.

CLAUSE STRUCTURE — also critical:
The "sentences" array is NOT a list of full sentences. It is a list of SHORT \
CLAUSES. Every comma in the story becomes a clause boundary. Each element ends \
with either a comma (，) or a sentence-final mark (。！？). Each element gets its \
own pinyin and its own short English translation.

For example, the sentence "我很着急，因为门坏了，我不能出去。" must be output as \
FOUR separate elements:
  {"hanzi": "我很着急，", ...}
  {"hanzi": "因为门坏了，", ...}
  {"hanzi": "我不能出去。", ...}

Each clause should typically be 5-15 characters. If a clause grows longer than \
~15 characters without a comma, insert a comma and split it.

Before you finish writing, COUNT how many words you used that are not in the \
lists. Aim for zero. If you have used more than 3, rewrite to remove them.

You MUST output valid JSON in the exact schema given."""


SYSTEM_TOPICS = """You suggest short story premises for a Mandarin graded reader. \
You are given the exact vocabulary the story must be told in. You propose \
premises that are tellable with THAT vocabulary, and that are interesting \
to an adult learner. Concrete, everyday, slightly varied. Output JSON only."""


def build_topic_prompt(new_words, due_words, free_words, count, user_hint="", phase=1):
    def fmt(entries, limit):
        return ", ".join(f"{e.hanzi}({clean_gloss(e.english)})" for e in entries[:limit])
    lines = ["Today's vocabulary pool (words the story may use):"]
    if phase == 1:
        lines.append(f"  CANDIDATE NEW words (pick from these): {fmt(new_words, 60)}")
    else:
        lines.append(f"  NEW words (must each appear): {fmt(new_words, 40)}")
    lines.append(f"  DUE words (must each appear >=1 time): {fmt(due_words, 60)}")
    lines.append(f"  FREE pool (any of these may be used freely): {fmt(free_words, 200)}")
    lines.append("")
    if user_hint.strip():
        lines.append(f"User hint: {user_hint.strip()}")
        lines.append("")
    lines += [
        f"Suggest {count} distinct story topics tellable with this vocabulary.",
        "Each topic: one short English phrase, 4-10 words, concrete and specific.",
        "Vary the settings and emotional tones. Avoid repeating the same scene type.",
        "",
        'Output JSON only, exactly: {"topics": ["...", "...", ...]}',
    ]
    return "\n".join(lines)


def _fmt_vocab_lines(entries):
    return "\n".join(
        f"  {e.rank}|{e.hanzi}|{e.pinyin}|{clean_gloss(e.english)}"
        for e in entries
    )


def build_story_prompt(new_words, due_words, free_words, target_length, range_pct,
                       user_topic="", phase=1, toggle=10):
    char_min = round(target_length * (1 - range_pct / 100))
    char_max = round(target_length * (1 + range_pct / 100))

    topic_line = (
        f"Write a story about: {user_topic.strip()}"
        if user_topic.strip()
        else "Choose your own topic - something concrete and interesting."
    )

    if phase == 1:
        new_section = f"""CANDIDATE NEW WORDS (pick from these):
Below is a small pool of candidate words you may choose to introduce today.
Pick UP TO {toggle} that fit naturally in your story. Not all need to be used.
Aim for each picked word to appear 2-3 times, but 1 time is acceptable.
Prefer words that fit the story, not words you force in.

CANDIDATES ({len(new_words)} words):
{_fmt_vocab_lines(new_words)}"""
        new_rules = f"""2. Pick UP TO {toggle} NEW words from the CANDIDATES list.
   Each picked word MUST appear at least once in the story.
   Do not pick words you won't use.
3. In your JSON output, list your picks in a top-level "new_words" array."""
    else:
        new_section = f"""NEW ({len(new_words)} words):
{_fmt_vocab_lines(new_words) if new_words else "  (none)"}"""
        new_rules = """2. NEW words should appear 2-3 times each if natural; 1 time is acceptable."""

    return f"""{topic_line}

TOPIC GUIDANCE: Prefer situations that can be told with abstract, social, or
everyday vocabulary — feelings, plans, opinions, small disagreements, questions,
news, observations, relationships. Avoid scenes that require specific objects,
specialized places, or rare nouns. If the requested topic needs words outside
the pool, reframe the story to avoid them.

LENGTH: roughly {char_min}-{char_max} Chinese characters ({target_length} target).
Try to reach at least {char_min} characters. If your first draft is shorter, add
more detail, dialogue, or description — do not add new plot. A shorter natural
story is acceptable if the vocabulary makes a longer one impossible.

VOCABULARY RULES (strict):
1. Use ONLY words from the pools below. No other Chinese words.
   Prefer HSK 1-3 level words when several options exist.
{new_rules}
4. DUE words must each appear AT LEAST 1 TIME in the story.
5. FREE words may appear any number of times, or not at all.
6. Prefer lower rank numbers when choosing among FREE words.

{new_section}

DUE ({len(due_words)} words, each >=1x):
{_fmt_vocab_lines(due_words) if due_words else "  (none)"}

FREE ({len(free_words)} words, any usage):
{_fmt_vocab_lines(free_words) if free_words else "  (none)"}

OUTPUT: Return ONLY valid JSON, no prose, no markdown fences. Schema:

{{
  "topic": "short English phrase describing the situation",
  "title_english": "A short proper English title (e.g. 'The Broken Door')",
  "new_words": ["和", "给", "东西"],
  "title_hanzi": "...",
  "title_pinyin": "...",
  "sentences": [
    {{
      "hanzi": "我很着急，",
      "pinyin": "wǒ hěn zháo jí,",
      "english": "I was very anxious,",
      "words": ["我", "很", "着急", "，"]
    }},
    {{
      "hanzi": "因为门坏了，",
      "pinyin": "yīn wèi mén huài le,",
      "english": "because the door was broken,",
      "words": ["因为", "门", "坏", "了", "，"]
    }},
    {{
      "hanzi": "我不能出去。",
      "pinyin": "wǒ bù néng chū qù.",
      "english": "I couldn't go out.",
      "words": ["我", "不", "能", "出去", "。"]
    }}
  ]
}}

RULES FOR sentences[]:
- Each element is ONE SHORT CLAUSE (5-15 characters typically).
- Each element ends in either a comma (，) or a sentence-final mark (。！？).
- Every comma in the story creates a new element.
- Each element has its own pinyin and short English translation.
- "words" is a flat array of word strings in order.
- Concatenating every string in words[] MUST reproduce that clause's "hanzi".

RULES FOR words[]:
- A flat array of word strings, in order.
- Each string is a word (or a punctuation mark).
- Punctuation marks are their own entries in words[].
- Do NOT include per-word pinyin, english, rank, or in_list fields.

Before finalizing, verify:
  - every sentences[] element is one short clause ending in ，。！？
  - every sentence's words[] concatenates to its "hanzi"
  - every word in your new_words[] list appears at least once in the story
  - every DUE word appears at least once
  - you used as few out-of-pool words as possible (aim for zero)
  - the JSON parses
"""


if __name__ == "__main__":
    from .state import load_state
    from .srs import get_today_cards
    st = load_state()
    today = get_today_cards(st, toggle=10)
    print(f"Phase 1: NEW candidates = {len(today['new'])}")
    print("first 5:")
    for e in today["new"][:5]:
        print(f"  {e.rank}  {e.hanzi}  {e.pinyin}  {clean_gloss(e.english)}")
    print(f"DUE={len(today['due'])} FREE={len(today['free'])}")
