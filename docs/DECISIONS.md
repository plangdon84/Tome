# Decisions and constraints (as of 2026-10-14)

This file records what is known about your setup and what follows from it.
It overrides the generic options in [REVIEW.md](REVIEW.md) and
[PLAN.md](PLAN.md) wherever the two disagree.

## Your setup

| Item | Value |
|---|---|
| Dev machine | MacBook Air (2020), Intel Core i3 1.1 GHz (2 cores), 8 GB RAM, Intel integrated graphics, macOS Ventura 13.6 |
| Books for the POC | *Harry Potter* 1–7 (one omnibus EPUB), *Cradle* 1–12 (DRM-free EPUBs) |
| Reading apps | Kindle app (mostly) and Apple Books, on a phone |
| Cloud model | Acceptable if it doesn't train on or keep your data. Prove the concept cheaply first. |
| Storage | SQLite |

## What follows from that

### 1. Running an LLM locally is off the table for now

A 2-core Intel i3 with 8 GB of RAM and no usable GPU acceleration would run
even a 3B model at only a few tokens per second. Processing one series would
take days, and the quality would be too low to judge the concept fairly.

**Decision:**
- **Language model:** a cloud API.
- **Local:** everything else. That covers EPUB parsing, SQLite, full-text
  search, and (later) embeddings with a small model like `bge-small` or
  `all-MiniLM`, which take minutes on a CPU.
- **Later:** the provider layer stays swappable, so a local model can be added
  if you get Apple Silicon hardware.

### 2. Cloud provider and data handling

- **Default choice:** the Anthropic API.
  - Commercial API terms say inputs and outputs are not used for training by
    default.
  - API logs are deleted after a limited period. Sources disagree on whether
    that is 7 or 30 days, so check the current Commercial Terms and Data
    Processing Addendum.
  - True **zero data retention** needs an enterprise agreement. "Not trained
    on, deleted after a short window" is what's realistic for a personal
    project. Describe it that way to authors as well.
- **Avoid free tiers of any provider.** Several free tiers do train on your
  inputs.
- **The provider layer stays swappable**, so this choice isn't permanent.

### 3. Cost estimate for the POC

The corpus is about **3.2M tokens** in total:
- *Harry Potter*: about 1.08M words, about 1.45M tokens.
- *Cradle*: about 1.3M words, about 1.75M tokens.

Listed API prices per million tokens (cached 2026-10-06; check before
spending):

| Model | Input $/MTok | Output $/MTok |
|---|---|---|
| Haiku 5.5 | 0.10 | 0.50 |
| Sonnet 5.5 | 2.00 | 10.00 |
| Opus 5.5 | 4.00 | 20.00 |

The Batch API halves these prices for jobs that aren't time-sensitive.

Estimated one-time processing cost for both series:

| Pass | Approx. tokens | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|
| Phase 1: chapter summaries (≈550 chapters) | ~5M in / ~0.45M out | **≈ $1** | ≈ $15 | ≈ $30 |
| Phase 2: entity/observation extraction | ~10M in / ~1.5M out | **≈ $2** | ≈ $35 | ≈ $70 |
| Per question asked | ~5–10k in / ~0.5k out | < $0.01 | ≈ $0.02 | ≈ $0.04 |

**Plan:**
1. Run every pass on a **sample** (about 3 chapters) with all three tiers.
2. Score the results on the eval set.
3. Run the full corpus only on the cheapest tier that passes.

**Expected total POC spend: under $50**, probably much less. You don't need
any cloud infrastructure: the code runs on your Mac and calls the API.

### 4. How the two series work as test sets

They're useful in different ways.

- ***Harry Potter* is the worst case for leaks.** Every LLM knows the whole
  plot, so any leak from the model's own memory will show up here.
  - Example: horizon at Book 3, ch. 10. Ask "Who is Scabbers?" The answer
    must not mention Pettigrew.
  - Example: horizon early in Book 6. Ask "Who is the Half-Blood Prince?" The
    answer must not mention Snape.

  If Tome stays spoiler-safe on HP, it is robust.
- ***Cradle* is the realistic case.** It's an indie, progression-fantasy series
  that the models know less about. It has a crunchy, ranked advancement
  system (Foundation → Copper → Iron → Jade → Gold → Lord → Overlord → Sage …)
  and many characters with titles and aliases.
  - It tests whether the answers are actually *useful*.
  - It tests whether "what does the power system allow at this point" can be
    answered.
- **Later: a truly obscure series.** Add one that models don't know at all, as
  a control.

Keep the public-domain *Monte Cristo* tests for CI and anything that gets
committed. HP and Cradle stay in your local `library/` and never go into git.

**The *Harry Potter* omnibus EPUB holds 7 books in one file.** The parser needs
to split it into books using the nested table of contents (with a manual
override file as a fallback). That's in Phase 1.

### 5. Getting your reading position from the Kindle app and Apple Books

These are the methods, in the order they'll be built:

1. **Chapter picker**, rounded conservatively to the last finished chapter.
2. **"Where am I?" via the share sheet:**
   - Select a sentence in Kindle or Apple Books, and share it to an **iOS
     Shortcut** that POSTs it to Tome.
   - Tome fuzzy-matches the text to a passage and sets the horizon there.
   - Apple Books adds an "Excerpt From … This material may be protected by
     copyright" footer to copied text. The matcher strips it.
3. **A screenshot via the share sheet:** OCR the screenshot, then match it.
   This is the fallback if Kindle limits copying.
4. **Kindle "% read" or location:** used only as a hint, because it varies by
   edition.

### 6. Where it runs

- **Phase 1–2:** a command-line tool on your Mac.
- **Phase 3:** a small web server on the Mac, which your phone reaches over
  Tailscale (free for personal use). The Mac needs to be awake. That's fine
  for a POC.
- **If it proves useful:** a small always-on host. The SQLite file and server
  are tiny, so this costs a few dollars a month at most.

### 7. How development works

- Code is written and tested here (in Claude Code sessions) against
  **public-domain books**. No copyrighted text ever enters the repo or this
  cloud session.
- You `git pull` on your Mac, put your EPUBs in `library/`, set
  `ANTHROPIC_API_KEY`, and run the pipeline on your own books.
- You report results and failures back. Failures become new eval cases.

### 8. Mac prerequisites (for when Phase 1 is ready)

- **Python 3.12+:** install with [uv](https://docs.astral.sh/uv/) (easiest)
  or Homebrew. Both work on Intel Macs running Ventura.
- **An Anthropic API key with a spending limit.** Set a monthly cap of about
  $20–50 in the Console.
- **Git.**
