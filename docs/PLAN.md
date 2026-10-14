# Plan: From Zero to a Reading Companion You Use

This plan follows on from [REVIEW.md](REVIEW.md). The guiding idea is to
**build the cheapest spoiler-safe baseline first, measure it, and add
structure only where it measurably helps.**

Each phase ends with a decision gate: continue, change course, or stop.

> **The concrete choices for your setup are in [DECISIONS.md](DECISIONS.md).**
> In short: an open-weight LLM on a rented GPU for your books (the smallest model that passes
> the evals), everything else local on an Intel Mac, SQLite, *Harry Potter* as
> the worst case for spoiler leaks, *Cradle* as the realistic usefulness test,
> and position capture via chapter picker plus the iOS share sheet.

---

## Core invariants (apply in every phase)

1. **One position axis.** Every passage has a monotonic integer `pos` across
   the series. The reader's horizon is a `pos`.
2. **`max_source_pos` on every derived artifact.** An artifact is visible only
   if `max_source_pos ≤ horizon`. This is enforced in one data-access layer.
3. **Process in reading order.** Any step that builds up knowledge
   (summaries, alias resolution, entity profiles) sees only text up to the
   point being processed.
4. **No LLM at reading time.** The LLM compiles the book into the database at
   ingestion. Answers are assembled from that database inside the app. See
   [ARCHITECTURE.md](ARCHITECTURE.md).
5. **Quote or drop.** Every observation carries a verbatim quote that must
   exist in its evidence passage.
6. **Conservative horizon.** If the position is uncertain, round backwards.
7. **No copyrighted text in git.** `library/` is gitignored. Tests use
   public-domain books.

---

## Phase 0: Foundations and eval harness (≈1 week)

Build the measuring stick before building anything else.

- [ ] Repo skeleton: Python project (uv), lint/format, pytest.
- [ ] SQLite schema v0, split into two files:
  - **The series pack**, read-only:
    - a manifest;
    - books, chapters and passages;
    - entities, aliases, observations, profiles, summaries and anticipated Q&A;
    - runs.
    Every derived table has `max_source_pos` and `run_id`.
  - **`user.sqlite`:** the library list, plus a stable horizon anchor for each
    series.
- [ ] Horizon-safe data-access layer. It is the *only* way to read derived
  tables, and tests try to bypass it.
- [ ] LLM provider abstraction:
  - An OpenAI-compatible adapter (vLLM, llama.cpp, Ollama) and an Anthropic
    adapter for public-domain development.
  - Each series has an allowed-provider list.
  - Track tokens on every call.
- [ ] Embedding abstraction pinned to one small model that can also run in a
  browser.
- [ ] Public-domain corpus: *The Count of Monte Cristo* plus one multi-book
  series (Barsoom or Oz).
- [ ] **Eval sets:**
  - **Spoiler cases:** `{horizon, question, must_not_include[]}`, run
    against what the app would show.
  - **Coverage cases:** `{horizon, question, expected_facts[]}`.
  - **A public set** on *Monte Cristo*.
  - **A private set** under `library/evals/`:
    - **Harry Potter:** about 30 worst-case leak questions.
    - **Cradle:** about 30 usefulness and power-system questions.
    - **Real questions** you write down while reading.
- [ ] Eval runner: reports leak rate, coverage, and quote-check pass rate.

**Gate:** the eval set runs end to end against a stub database.

## Phase 1: Parse, search, and summaries (≈2 weeks)

**EPUB → passages → keyword + meaning search → rolling summaries.** This is
the cheapest database that can already answer recap and "where have I seen
this?" questions.

- [ ] EPUB parser:
  - Spine order.
  - **Splitting an omnibus into its books**, from the nested TOC, with a
    manual override file.
  - Chapter detection.
  - Stripping front and back matter.
  - Splitting chapters into passages of about 150–400 words, each with a
    `pos`.
- [ ] Indexes: FTS5 plus passage embeddings.
- [ ] Rolling chapter summaries, book recaps, and "story so far" rollups.
- [ ] CLI:
  - `tome ingest`
  - `tome search --at "b3 ch10" "scabbers"`
  - `tome recap --at "b2 ch1"`
- [ ] GPU pod runner script: upload, start vLLM, ingest, download the SQLite
  file, destroy the pod.
- [ ] Compare open-model sizes (about 8–14B vs about 70B) for summary quality
  on about 3 chapters.

**Gate:** recaps are accurate and spoiler-free. Search returns the right
passages for "where have I seen X?"

## Phase 2: The knowledge compiler (≈4–5 weeks). This is the core of the POC.

- [ ] Mention extraction (structured JSON output) and **incremental alias
  resolution in reading order**, with `established_at`. Test it on the
  *Monte Cristo* reveals and on Scabbers / Pettigrew.
- [ ] Observations: natural-language sentence, structured fields, status
  (stated / claimed_by / inferred), and quote span. The **quote check** drops
  any observation whose quote doesn't verify.
- [ ] Relationships with a `pos`.
- [ ] Entity profiles at checkpoints, built from the previous profile plus new
  observations. Includes a support check.
- [ ] Anticipated Q&A per chapter, cited and limited to text up to that point.
- [ ] Ingestion audit report: how many observations were dropped by the quote
  check, how many profile sentences were flagged, and leak-eval results.
- [ ] Model-size comparison on the same sample. Keep the smallest model that
  passes.

**Gate:** the database passes the spoiler eval with zero leaks, and the quote
check passes for the vast majority of observations.

## Phase 3: The app, entirely on-device (≈3 weeks)

- [ ] Query pipeline (in Python first, mostly SQL):
  1. Horizon filter.
  2. Match entities in the question against the horizon-filtered alias list.
  3. Route the question by type.
  4. Look up or search the database.
  5. Assemble the answer with evidence links.
- [ ] Coverage eval on real questions. This is **the viability test** (see
  ARCHITECTURE.md).
- [ ] **A PWA** that works offline and needs no server:
  - SQLite-WASM and an in-browser embedding model.
  - Pack import (file picker, share sheet, or link), a library view, and a series picker.
  - An always-visible horizon bar for each series.
  - Ask box and recap button.
  - Answer → evidence → passage.
- [ ] Position capture:
  - Chapter picker.
  - Paste a sentence, matched fuzzily and locally against passages.
  - An iOS Shortcut that hands selected text to the PWA, for example by
    opening a URL with the text as a parameter.
- [ ] "I finished a chapter" button. The horizon only moves forward when you
  move it.

**Gate:** you use it through one whole book of a real series, and the
coverage on real questions is good enough that you keep using it.

## Phase 4: Friends beta (≈ongoing)

- [ ] Distribution: friends install the PWA and load a series database. They
  must own the books (see the sharing note in ARCHITECTURE.md).
- [ ] Each reader keeps their own horizon on their own device. A series is
  compiled once.
- [ ] Feedback button on answers ("wrong", "spoiled me", "missing"). Every
  "spoiled me" becomes a new eval case.
- [ ] Mystery / unresolved-question tracking (first version).

## Phase 5: Decide on commercial direction

Use the author conversations (see [AUTHOR_OUTREACH.md](AUTHOR_OUTREACH.md))
and the beta experience to choose between staying personal, going open
source, or building an author-sanctioned companion pilot with one author.

---

## Things deliberately left out until there's evidence they're needed

Any LLM at reading time, graph database, ontology engine, contradiction reconciliation, magic-system
modeling, maps, timeline UI, community editing, public wiki, native mobile
apps (the PWA comes first), and DRM handling of any kind.

## Resolved questions

Your answers to the original open questions (hardware, books, reading app,
cloud policy, storage) are recorded in [DECISIONS.md](DECISIONS.md).
