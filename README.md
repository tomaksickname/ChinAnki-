# Chinanki

A daily Mandarin reading system: generate a short Chinese story each day, render it in a custom reader with pinyin, glosses, and audio, and use SRS to schedule vocabulary review.

## Problem: Input

I started learning Mandarin from absolute zero. The standard advice — use a frequency list, do sentence mining, listen to podcasts — assumes a base of vocabulary I didn't have yet. Frequency lists don't help until the list makes sense. You can't follow a podcast at zero words. Anki with sentence mining is mentally taxing and pulls vocabulary from sources above my level.

What I needed was the opposite: a daily drip of simple, controlled Chinese that I could actually get through, where the vocabulary was narrow enough to be learnable, and the stories were short enough to finish in five minutes. Comprehensible input, delivered at a controlled difficulty, with the SRS engine quietly driving the vocabulary progression.

## Problem: Output

I built Chinanki to generate that content. The design assumed an LLM could write a story constrained to a specific vocabulary list — only introduced words, plus a small batch of new words, plus words due for review. The ambition was a self-contained daily habit: read one story, hear it, absorb the words, come back tomorrow. Repeat for 12–24 months.

What I found: **the design assumes the LLM can produce coherent narratives under a vocabulary constraint that, at low SRS state, is too tight.** When you've introduced 10–100 words, the pool is so small that the model can't write anything that reads like a story. It produces sentences that are technically valid but narratively monotone and semantically thin — chains of unrelated clauses with no through-line, no tension, no resolution. Sometimes outright nonsense.

The flaw is structural, not fixable with prompt engineering alone. When the model is given 30 words and told to write a 200-character story that "reads naturally," it can't. The task is impossible for the vocabulary budget.

## What this project demonstrates

I built Chinanki to solve my own bottleneck, then iterated on it honestly when the first design didn't work. The project demonstrates:

- **Constrained LLM generation with a real validator.** The system doesn't trust a single model output. Every story is parsed, checked for structural consistency (word tokens must concatenate back to their sentence), checked for vocabulary compliance, and retried on failure. The constraint is enforced by code, not by prompt.
- **SRS integrated with daily content generation.** A story is not just reading material; it is the mechanism by which vocabulary is introduced and scheduled. The system reads the SRS state, decides which words are due today, generates a story that contains them, then updates the scheduling based on whether the words actually appeared.
- **Explicit failure handling.** Soft vs. hard constraint distinction is designed in. Structural failures retry. Coverage failures are dropped silently and the words stay due for the next day.
- **Evaluation-first design.** The system's whole purpose is to make reading possible at a specific difficulty. Every design decision was made against that criterion, including the decision to acknowledge that the original design wasn't producing what it promised.

## What actually happened

**The frequency list was missing structural essentials.** The list is podcast-derived and doesn't match narrative needs. It was missing 了, 吗, 家, 水, 听, 打, and hundreds of other words that any coherent sentence requires. The list has been patched repeatedly with hand-curated essentials, but the fundamental misalignment remains. Even at 300 introduced words, the effective story-tellable vocabulary was much thinner than the raw count suggested.

**The system is functional; the design is not yet useful at my level.** Generation works, validation works, reading works, audio works, SRS works. But the output quality under narrow vocabulary is not what the original design assumed. The system will not become what it was designed to be until I have roughly 1,000+ known words.

## Current workaround: HSK 1 mode

For the immediate need — getting enough reps on the basics to build a foundation — I'm currently telling the model to write an HSK 1 story manually, ignoring the frequency list and using whatever HSK 1 words it needs. This produces stories that look like HSK 1 should: simple sentences, high repetition of a small set of words, short and clear.

At this level, the system's job is not to schedule vocabulary acquisition but to give daily reps on a fixed vocabulary until the words are automatic. Then the vocabulary grows and the original design becomes viable.

## Solution: components as built

### Vocabulary list
A JSON array of ~3,100 Mandarin words, each with hanzi, pinyin, English gloss, traditional form, part-of-speech, Zipf score, corpus count, and word length. Ranks are non-contiguous — curation dropped entries, leaving gaps. The list is a curated artifact, patched over multiple rounds with hand-added essentials at the top of the rank order.

### SRS engine
Standard SM-2 with learning steps `[1, 10, 30]` minutes, graduating interval of 1 day, starting ease factor of 2.5. Every word starts as `state: "new"`. When introduced, it's rated `"good"` three times, graduating it into `state: "review"` with a due date one day out. Due words get rated `"good"` once, growing their interval.

### Daily freeze
The first successful generation of the day picks a NEW batch and a DUE batch, rates them, and freezes them in `state["today"]`. Subsequent generations the same day reuse the frozen batch without re-rating.

### Story generation
The generator sends DeepSeek three buckets:

- **NEW candidates** — 60 un-introduced words drawn from the top of the frequency pool. The model picks 5–10 that fit the story. Picks that don't get used are dropped.
- **DUE words** — words scheduled for review today. The model weaves them in. Words that don't appear stay due and surface again tomorrow.
- **FREE glue** — the top 300 highest-frequency words in the pool, always available for connective tissue.

The prompt enforces a clause-per-element structure: one short clause per entry in the `sentences[]` array, each ending in a comma or sentence-final mark. This makes the story render as short rows in the reader.

### Validation
- Every sentence's `words[]` tokens must concatenate to the `hanzi` string.
- Every non-punctuation word must be within the allowed pool (or tagged as out-of-pool).
- Every picked NEW word must appear at least once (soft — dropped if unused).
- Every DUE word must appear at least once (soft — skipped if not).
- Sentence length total must be within 20% of target.

Structural failures are hard failures that trigger a retry. Coverage failures are soft and dropped downstream.

### Retry loop
Up to 15 attempts per generation, cycling through three target lengths (initial, +15%, +30%). With soft DUE and soft NEW filtering, success on the first or second attempt is typical.

### Reader
A centered three-tier layout per sentence: hanzi, pinyin, English gloss (only under the current cursor word). Each word column contains all three stacked, so hanzi is always centered over its pinyin.

Keyboard-driven navigation: ←/→ moves word by word, ↑/↓ moves clause to clause, Shift toggles sentence translation and plays its audio. Clicking a word shows its gloss and plays its audio. The reader auto-scrolls to keep the current cursor sentence vertically centered.

### Audio
Azure TTS via `zh-CN-XiaoxiaoNeural`. Three caches: per-word, per-clause, per-story. First play triggers an API call (~0.5s round trip). Subsequent plays read from cache.

### Pacing sweep
A target reading time is set in minutes. The story's characters are divided into per-character units. A hard vertical edge sweeps left-to-right across each sentence at constant speed, revealing a cool-to-hot gradient underneath. Everything to the left is tinted; everything to the right is black. When a sentence's allocation runs out, its tinted text fades to black and the sweep moves to the next sentence.

The sweep is a metronome, not a driver. It runs independently of cursor movement.

## Key design decisions

### One story per day, not a lesson sequence
The vocabulary list is the curriculum. There's no fixed progression. Words are introduced as needed, drawn from a candidate pool that biases toward high-frequency entries but rotates daily. This mirrors how comprehensible input works: you read things that are just barely accessible and the vocabulary accretes.

### Model-picked NEW words, not rank-ordered introduction
The first iteration introduced NEW words strictly in rank order. This failed because the frequency list is podcast-derived and doesn't match narrative needs. The revised design gives the model 60 candidates each day and lets it pick 5–10 that fit the story's needs.

### Soft DUE constraint
Requiring every due word to appear creates a hard failure mode: if the model can't fit a word in naturally, it either forces an awkward sentence or fails validation entirely. The soft version — "if it appears, rate it; if it doesn't, skip it" — trades a small amount of SRS strictness for a large amount of generation reliability.

### Clause-per-element structure
Full-sentence entries produce rows too long to read comfortably. Splitting at commas produces one short clause per row, more legible and matching the natural rhythm of spoken Chinese.

### Pacing without numbers
The session sweep is a visual metronome, not a numeric countdown. You read pace by watching how fast it moves. Anxiety-inducing timers degrade reading comprehension. The sweep is meant to be a soft guide, not a deadline.

### Wishlist mode
When the model uses a word outside the allowed pool, it doesn't fail the generation. It gets tagged with a best-effort pinyin (via `pypinyin` for out-of-pool words) and lands in a "wishlist" at the bottom of the story. Recurring wishlist entries are candidates for hand-adding to the frequency list.

## Architecture

[Browser reader] ⇄ [Python stdlib HTTP server] ⇄ [DeepSeek API + Azure TTS + JSON files]

Backend is pure Python 3.9 standard library except for `requests` and `pypinyin`. No Flask, no build step. Server runs on `127.0.0.1:8765`.

## Technical stack

Python 3.9 + stdlib HTTP server, vanilla JS, DeepSeek API (`deepseek-chat`), Azure Speech for TTS, IBM Plex Sans, JSON files with atomic writes.

## Build timeline

Roughly 3 weeks of iterative work:
- Week 1: Vocabulary list loading, SRS engine, basic generation + validation loop.
- Week 2: Frequency list patching, prompt size reduction, retry ladder, soft DUE/NEW policies, clause-per-element structure.
- Week 3: Reader redesign, pacing sweep, audio caching, Azure TTS integration, mobile iCloud sync.

## Open problems and roadmap

Three areas where I know the current system is weak and have concrete plans to fix them:

**Hard HSK filter not yet implemented.** Current workaround is prompt-level ("write an HSK 1 story, ignore the frequency list"), which the model mostly follows but not reliably. A structural filter — replacing the FREE and NEW pools with an HSK 1+2 whitelist — would enforce the constraint at the data layer. This is the immediate next step.

**Frequency list quality.** The list is podcast-derived and missing structural essentials. Every patch has been reactive. A more systematic approach would be to compare the list against a reference HSK or narrative-frequency list and add all missing common words in one batch.

**Paste-import.** A textarea where I can paste a story from another LLM (in a structured JSON format) and have it processed into the same reader format. This lets the system benefit from stories I generate elsewhere without requiring the Chinanki generator to be good at HSK 1.

## What I learned

- A frequency list derived from one register (podcast speech) doesn't match another register (narrative prose). The list is the curriculum, and its shape determines what kinds of stories the system can tell.
- LLMs obey vocabulary constraints reliably at 60 words, poorly at 300, badly at 1,000. The candidate pool size directly determines reliability.
- The distinction between "the model failed" and "the harness failed" matters enormously. Half the problems during development were model drift, and half were self-inflicted.
- Hard constraints are much harder to enforce than soft constraints. The system improved dramatically when DUE coverage and NEW picks became soft rather than hard — retries dropped, quality improved, and the underlying SRS still worked because words that skipped came back the next day.
- Building a constrained LLM application is mostly a matter of building a good validator. The model does what it does; the system's job is to catch failures early and either fix them or route around them.

## Running it

1. `cd /Users/ed/Desktop/Chinanki`
2. `source /Users/ed/Desktop/chinesefreqsorter/.venv/bin/activate`
3. `python -m chinanki.server`
4. Open `http://127.0.0.1:8765`

Environment variables: `DEEPSEEK_API_KEY`, `AZURE_TTS_KEY`, `AZURE_TTS_REGION`, `AZURE_TTS_VOICE`, `TTS_BACKEND`.
