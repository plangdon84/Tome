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

- [x] Repo skeleton: Python project (uv), lint/format, pytest.
- [x] SQLite schema v0, split into two files (`tome/migrations/`):
  - **The series pack**, read-only:
    - a manifest;
    - books, chapters and passages;
    - entities, aliases, observations, profiles, summaries and anticipated Q&A;
    - runs.
    Every derived table has `max_source_pos` and `run_id`.
    *Done. Also added `entity_identities` (reveals such as Busoni = the Count),
    `mentions` and `embeddings`, and a trigger that enforces quote-or-drop.*
  - **`user.sqlite`:** the library list, plus a stable horizon anchor for each
    series.
- [x] Horizon-safe data-access layer. It is the *only* way to read derived
  tables, and tests try to bypass it. *(`tome/horizon.py`: horizon-filtered
  TEMP views plus an SQLite authorizer that refuses direct reads.)*
- [x] LLM provider abstraction (`tome/llm/`):
  - An OpenAI-compatible adapter (vLLM, llama.cpp, Ollama) and an Anthropic
    adapter for public-domain development. *OpenAI-compatible adapter done
    (plus OpenRouter, with a JSON-schema helper). The Anthropic adapter is
    deferred: OpenRouter covers public-domain development.*
  - Each series has an allowed-provider list.
  - Track tokens on every call.
- [x] Embedding abstraction pinned to one small model that can also run in a
  browser. *(Xenova/bge-small-en-v1.5, quantized ONNX at a pinned revision.)*
- [x] Public-domain corpus: *The Count of Monte Cristo* plus one multi-book
  series (Barsoom or Oz). *Monte Cristo (Standard Ebooks, Gutenberg
  fallback) and Oz books 1–5 (DECISIONS.md §11). The Gutenberg Monte Cristo,
  whose five volumes are nested in its table of contents, doubles as an
  omnibus-split fixture. Public eval sets for both.*
- [x] **Eval sets:**
  - **Spoiler cases:** `{horizon, question, must_not_include[]}`, run
    against what the app would show.
  - **Coverage cases:** `{horizon, question, expected_facts[]}`.
  - **A public set** on *Monte Cristo*.
  - **A private set** under `library/evals/` *(templates committed in
    `evals/templates/private/`; `tome eval init-private` copies them. You
    fill in the cases.)*:
    - **Harry Potter:** about 30 worst-case leak questions.
    - **Cradle:** about 30 usefulness and power-system questions.
    - **Real questions** you write down while reading.
- [x] Eval runner: reports leak rate, coverage, and quote-check pass rate.

**Gate:** the eval set runs end to end against a stub database. ✅ *Met: `uv run
tome eval run --stub` shows 0/11 leaks, 11/11 coverage and an 85.7%
quote-check pass rate. The stub plants two bad quotes and one unstated
reveal on purpose, and a
meta-test confirms that an answerer which ignores the horizon is caught.*

## Pre-Phase 1: Your setup (status 2026-10-21)

The things only you can do before Phase 1 runs on real books. Phase 1 can
start now: the open items below are eval cases, which keep being written
alongside it.

- [x] Mac set up ([MAC_SETUP.md](MAC_SETUP.md)), with the AWS command line
  and Claude Code installed.
- [x] GPU quota increase on AWS (DECISIONS.md §12). *Approved.*
- [x] Parse test on the *Harry Potter* omnibus. *`split = "toc"` gives 7 books
  with the right chapter counts (17, 18, 22, 37, 38, 30, 36 + epilogue);
  3,974 passages and 1,090,408 words, the same totals as the one-book parse.
  The only warning is an empty `Pottermore.com` page, which is skipped.*
- [x] *Cradle* books 1–3 (*Unsouled*, *Soulsmith*, *Blackflame*) are in
  `library/` as EPUBs.
- [x] First pass of private *Harry Potter* eval cases (`library/evals/`).
  *11 spoiler and 14 coverage cases, all passing `tome eval check` against a
  parse-only pack. On that pack the baseline answerer leaks 0/11 and scores
  38.5% coverage: a text-only starting point, since there is no compiler yet.*
- [x] *Harry Potter* series config (`library/series/harry-potter.toml`):
  copyrighted, `vllm-local` only.
- [ ] More *Harry Potter* spoiler cases, up to about 30.
- [ ] *Cradle* eval cases and a first run: build a parse-only pack from books
  1–3, then `tome eval check` and `tome eval run`.

## Phase 1: Parse, search, and summaries (≈2 weeks)

**EPUB → passages → keyword + meaning search → rolling summaries.** This is
the cheapest database that can already answer recap and "where have I seen
this?" questions.

- [x] EPUB parser *(done early, in Phase 0)*:
  - Spine order.
  - **Splitting an omnibus into its books**, from the nested TOC, with a
    manual override file. *(Layout TOML: `split = "toc"` or `"manual"`;
    confirmed on the real HP omnibus.)*
  - Chapter detection.
  - Stripping front and back matter.
  - Splitting chapters into passages of about 150–400 words, each with a
    `pos`.
- [x] Indexes: FTS5 plus passage embeddings *(done early: `tome pack build-text --embed`)*.
- [x] Rolling chapter summaries, book recaps, and "story so far" rollups.
  *(`tome/summarize.py`. Chapters run one at a time in reading order, with each
  rollup rebuilt from all of its book's chapter summaries. Oz book 1 compiled
  live 2026-11-07 with `Qwen/Qwen2.5-7B-Instruct`: no leaks in the 4 book 1
  spoiler cases, and all 5 book 1 coverage cases passed. The 7B model still makes
  factual slips, so the Gate below stays open until the model comparison. No
  resume after a failed run yet. `tome/names.py` flags names the text hasn't
  used yet and regenerates once. On a second live run that removed "Dorothy Gale"
  with no flagged names left. A false alarm on "Princess" also rewrote chapter 14,
  and the end-of-book rollup that followed dropped the Wicked Witch of the West
  (coverage case oz-c06), so rollups are fragile to small changes in their input.)*
- [x] CLI:
  - `tome ingest`
  - `tome search --at "b3 ch10" "scabbers"` *(exists: keyword search, horizon-filtered)*
  - `tome recap --at "b2 ch1"`
- [x] GPU pod runner script: upload, start vLLM, ingest, download the SQLite
  file, destroy the pod. *(`scripts/gpu_pod.py`, with a self-terminate timer and
  SSH open to one IP only. The full `run` passed 2026-11-06 on `g5.xlarge` in
  us-east-1: vLLM served `Qwen/Qwen2.5-7B-Instruct`, `tome llm smoke` succeeded,
  and a `build-text` Oz pack came back. `tome ingest` ran on it 2026-11-07, on
  `g5.xlarge` and `g6.xlarge`. `g6e.xlarge` has not launched: AWS Support
  (case 179270307500931) confirmed a real capacity shortage, not an account
  limit, so retry launches hourly across us-east-1 and us-east-2.)*
- [ ] Compare open-model sizes (about 8–14B vs about 70B) for summary quality
  on 12 chapters (three windows of 4 consecutive chapters), in two stages:
  automated on public domain via OpenRouter, then judged by you on
  HP/Cradle on the pod. See DECISIONS.md §12. *Stage A done 2026-11-07
  (`tome compare`, [results](results/model-comparison-stage-a.md)): Qwen 2.5
  7B against 72B on Oz 1–2 and Monte Cristo ch 1–34. No summary leaks for
  either model. The 72B model had 15 vs 34 contradicted sentences on Oz and 7 vs 36
  on Monte Cristo, and a 7B error carried through four rollups in a row.
  Coverage was a wash. Follow-ups: the search fallback no longer leaks the
  Sinbad case, and rollups are checked sentence by sentence against their
  chapter summaries, as a warning only, since 7B's rewrites added as many errors as
  they fixed. Round 2 done 2026-11-08
  ([results](results/model-comparison-round-2.md)): nine candidates, two runs
  each, every model pinned to one OpenRouter host. No leaks. In contradicted
  chapter-summary sentences (Oz + MC, run 1 / run 2), Llama 3.3 70B led with
  0 / 4, then Qwen 2.5 72B 8 / 5 and Qwen3 14B 8 / 10. Qwen 2.5 7B had
  27 / 29 and gpt-oss 20B 36 / 31. Stage B candidates: Qwen3 14B (FP8, thinking
  off) and Llama 3.3 70B (AWQ). Pinning did not make runs repeatable.
  **Decided 2026-11-09:** lead with Llama 3.3 70B, and fall back to Qwen3 14B
  only without `g6e.xlarge` capacity (DECISIONS.md §12). A follow-up found that
  keeping only what two drafts agree on is a poor filter: it removed 59% of
  judged errors but also 21% of good sentences. Stage B (on the pod) is next.*
- [ ] Stage B: judge Llama 3.3 70B at AWQ 4-bit on HP/Cradle, using the
  windows in DECISIONS.md §12. Start with a 5-chapter trial
  (`gpu_pod.py --model llama-3.3-70b`, then `tome ingest --max-chapters 5`),
  because it is the tightest fit on the L40S. Judge Qwen3 14B (`--model
  qwen3-14b`) the same way as the fallback.

### Summary accuracy (before the Gate)

Stage A found the summary errors are mostly wrong attribution and causation
(who said or did something, which person, what caused what). They spread:
each summary is read by the next chapter's prompt and by the rollups. Fix them
where they start, and measure the fixes against hand-checked chapters rather
than the judge alone, since the judge was right only about 5 times in 9.

- [ ] **Gold set.** Hand-mark every factual error in about 10 public-domain
  chapters (for example Oz book 2 ch 15–24, which hold the Jellia,
  flying-machine and pill-wish slips). This measures how often the judge
  is right and how many errors it misses. Every pipeline change below is
  scored against it. Each confirmed error becomes a regression case in
  `evals/public/`.
- [ ] **Check each chapter summary against its own chapter, before it is
  stored or fed forward.**
  - Run it on the pod, with the per-sentence yes/no prompt the rollup check
    uses (`tome/summarize.py`).
  - Catching an error here keeps it out of every later prompt and rollup.
  - Record flagged sentences in the run stats, as the rollup check does.
- [ ] **Repair by deleting, never by rewriting sentences.**
  - Drop a flagged sentence, or regenerate the whole summary once, check it
    again, and keep the version with fewer flags.
  - Stage A showed that rewriting flagged sentences added about as many
    errors as it fixed, and a second check passed them.
  - A missing detail costs coverage; a wrong one misleads the reader.
  - Measure the coverage cost on the public evals.
- [ ] **Check from a second model family.**
  - Llama 3.3 70B fills the L40S, so it checks its own work while it
    compiles.
  - After compiling, swap in Qwen3 14B to re-check every summary and rollup.
    This audit pass only adds flags to the review queue, since the pack is
    already built.
  - With the fallback model, Qwen3 14B and Gemma 3 12B (FP8, about 30 GB
    together) fit on one L40S, so a second-family checker can run inline.
  - On a 24 GB instance, run the audit pass after compiling, the same way.
- [ ] **Review queue.** A `tome review` command lists, for a pack:
  - flagged sentences, ranked by risk: identity statements, reveal chapters
    and names first;
  - sentences the two checkers disagree on.
  Reading this replaces reading every summary. Also run it before Phase 2
  results are trusted.

Not worth building: writing each summary twice and keeping only what both
drafts agree on (results, round 2 follow-up). Agreement can be at most a
low-weight signal in the review queue.

**Gate:** recaps are accurate and spoiler-free. Search returns the right
passages for "where have I seen X?" *"Accurate" is measured on the gold set:
the number of factual errors left in its chapters, after the checks and
repairs above, with a threshold set after the first measurement.*

## Phase 2: The knowledge compiler (≈4–5 weeks). This is the core of the POC.

- [ ] Mention extraction (structured JSON output) and **incremental alias
  resolution in reading order**, with `established_at`. Test it on the
  *Monte Cristo* reveals and on Scabbers / Pettigrew.
- [ ] Observations: natural-language sentence, structured fields, status
  (stated / claimed_by / inferred), and quote span. The **quote check** drops
  any observation whose quote doesn't verify.
- [ ] **Quote-grounded summaries.**
  - Each summary sentence carries a short supporting quote. The quote is
    verified mechanically against the chapter text: no model, deterministic.
  - The checker then compares one sentence with one quote, rather than with
    the whole chapter.
  - A sentence with no verified quote is dropped, the same quote-or-drop rule
    as observations (invariant 5).
  - Score it on the gold set against Phase 1's chapter check.
- [ ] Relationships with a `pos`.
- [ ] Entity profiles at checkpoints, built from the previous profile plus new
  observations. Includes a support check, which uses Phase 1's checker,
  repair-by-deletion and review queue.
- [ ] Anticipated Q&A per chapter, cited and limited to text up to that point.
- [ ] Ingestion audit report: how many observations were dropped by the quote
  check, how many profile sentences were flagged, and leak-eval results. It
  also gives the error rate on the gold set, and it is the summary page of
  `tome review`.
- [ ] Model comparison on the same sample. Llama 3.3 70B is the default
  (DECISIONS.md §12). Re-test Qwen3 14B, the fallback, on extraction, since
  structured extraction may rank models differently from summaries.

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
