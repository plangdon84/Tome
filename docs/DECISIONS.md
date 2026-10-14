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
| Cloud model | Self-hosted open-weight model on a rented GPU for copyrighted books (no AI-company APIs). Prove the concept cheaply first. |
| Storage | SQLite |

## What follows from that

### 1. Running an LLM locally is off the table for now

A 2-core Intel i3 with 8 GB of RAM and no usable GPU acceleration would run
even a 3B model at only a few tokens per second. Processing one series would
take days, and the quality would be too low to judge the concept fairly.

**Decision:**
- **Language model:** an open-weight model on a rented cloud GPU (see §2).
- **Local:** everything else. That covers EPUB parsing, SQLite, full-text
  search, and (later) embeddings with a small model like `bge-small` or
  `all-MiniLM`, which take minutes on a CPU.
- **Later:** the provider layer stays swappable, so a local model can be added
  if you get Apple Silicon hardware.

### 2. Where the model runs: a self-hosted open model for your books

**Rule:** copyrighted books are processed only by an **open-weight model
running on a GPU you rent**. No AI company's API ever receives their text.

**How it works:** take a "pod" approach, so no endpoint is ever exposed.

1. Rent a GPU pod by the hour from a GPU cloud (RunPod, Vast.ai, Lambda,
   Modal, or a hyperscaler's spot GPUs).
2. Upload the EPUBs and the Tome code to the pod.
3. Run **vLLM** (or llama.cpp or Ollama) on the pod itself, serving an
   open-weight model.
4. Run the ingestion pipeline against `localhost` on the pod.
5. Download the resulting SQLite database to your Mac.
6. **Destroy the pod and its disk.**

**What this does and doesn't protect:**
- The text never reaches a company that trains models.
- You still trust the GPU host, the way you trust any cloud provider with a
  disk. They have no model-training business and normal cloud terms apply.
- You control deletion completely.
- The pitch to authors is stronger: "processed on private rented hardware
  with an open model, deleted afterwards."

**Model choice:**
- Test a small class (about 8–14B, which fits a 24 GB card) against a large
  class (about 70B quantized, which needs 48–80 GB) on the eval sample.
- Use the smallest one that passes.
- Pick specific models when we get there. The open-weight landscape changes
  every few months.

**Public-domain development books can use any provider**, including a cheap
API. There's no copyright or consent issue, and it makes iterating faster.
The code tags each series with an allowed-provider list, so a copyrighted
series *cannot* be sent to a non-self-hosted provider by accident.

**Provider layer:**
- **Primary adapter:** OpenAI-compatible chat. vLLM, llama.cpp, and Ollama
  all speak it.
- **Secondary adapter:** an Anthropic adapter, kept for public-domain
  development and comparison.

### 3. Cost estimate for the POC

The corpus is about **3.2M tokens** in total:
- *Harry Potter*: about 1.08M words, about 1.45M tokens.
- *Cradle*: about 1.3M words, about 1.75M tokens.

Workload estimates:
- **Summaries:** about 5M tokens in and 0.45M out.
- **Extraction:** about 10M tokens in and 1.5M out.

Rough GPU rental prices (check current prices; marketplace prices vary):

| GPU | Typical $/hr | Fits |
|---|---|---|
| RTX 4090 / L4-class (24 GB) | ~$0.30–0.80 | 8–14B models |
| A100 80GB | ~$1–2 | ~70B at 4-bit |
| H100 80GB | ~$2–3 | ~70B at 4-bit, faster |

vLLM processes many requests at once. Chapter summaries chain within a book,
but 19 books can run in parallel, and extraction calls are independent of
each other. A rough throughput estimate:
- **8B model:** both series' summaries take well under an hour, and
  extraction takes 1–2 hours.
- **70B model:** expect a few hours for everything.

**Expected spend:**
- About **$5–20 per full run** of both series.
- Add a few dollars for the model comparison runs.
- About **$1–5** of API use for public-domain development.
- A **POC total under $50** still holds.

**Cost-control rules:**
- Always use auto-shutdown or a time limit on pods. An idle GPU left running
  is the main way to waste money.
- Prefer providers with per-second billing.

### 3a. Answering questions while you read

Ingestion is a batch job. Questions arrive one at a time while you read, and
keeping a GPU running all day to answer them is wasteful. Options:

| Option | Privacy | Cost | Experience |
|---|---|---|---|
| **Serverless GPU** (RunPod Serverless, Modal) running the same open model, scaling to zero | Same as ingestion: rented hardware, no AI company | Pay per second of use, so cents per reading session | Cold start of roughly 30s to a few minutes on the first question, then fast |
| Pod started at the beginning of a reading session | Same | ~$0.30–0.80/hr while it's up | Fast, but you have to remember to stop it |
| Small model (~3B) on your Mac | Fully local | Free | Slow (about a minute per answer) and weaker answers |
| Precomputed answers only (recaps, entity profiles at each chapter) | Fully local at read time | Free at read time | Instant, but no free-form questions |

**Recommendation:**
- **Precompute** recaps and entity profiles at chapter checkpoints during
  ingestion. That covers "recap" and most of "who is X" with **no** model
  needed at read time.
- Use **serverless GPU** for free-form questions.
- Accept the cold-start delay for the POC.

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
- You `git pull` on your Mac and put your EPUBs in `library/`.
- A helper script uploads them and the code to a rented GPU pod, runs
  ingestion there, downloads the SQLite file, and destroys the pod.
- You report results and failures back. Failures become new eval cases.

### 8. Mac prerequisites (for when Phase 1 is ready)

- **Python 3.12+:** install with [uv](https://docs.astral.sh/uv/) (easiest)
  or Homebrew. Both work on Intel Macs running Ventura.
- **A GPU cloud account with a prepaid balance.** About $20–50, so cost
  can't run away.
- Optionally, an API key with a spending cap for public-domain development.
- **Git.**
