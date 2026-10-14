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
   if `max_source_pos ≤ horizon`.
3. **Process in reading order.** Any step that builds up knowledge
   (summaries, alias resolution, entity profiles) sees only text up to the
   point being processed.
4. **Cite or drop.** Every claim in an answer cites passages. A citation past
   the horizon is a hard failure.
5. **Conservative horizon.** If the position is uncertain, round backwards.
6. **No copyrighted text in git.** `library/` is gitignored. Tests use
   public-domain books.

---

## Phase 0: Foundations and eval harness (≈1 week)

Build the measuring stick before building anything else.

- [ ] Repo skeleton: Python project (uv or poetry), lint/format, pytest.
- [ ] Provider abstraction: one `LLMClient` interface (an OpenAI-compatible
  adapter for vLLM, llama.cpp, or Ollama first; an Anthropic adapter for
  public-domain development) and one `Embedder` interface.
  - Each series has an allowed-provider list, so copyrighted books can only
    go to self-hosted models.
  - Track tokens on every call.
- [ ] GPU pod runner script: upload, start vLLM, ingest, download the SQLite
  file, destroy the pod.
- [ ] Download the public-domain corpus: *The Count of Monte Cristo* plus one
  multi-book series (Barsoom or Oz).
- [ ] **Spoiler eval set**, written by hand, about 40–60 cases:
  `{horizon, question, must_include[], must_not_include[]}`.
  Example: horizon = Monte Cristo ch. 30; Q: "Who is the Abbé Busoni?";
  must_not_include: "Dantès".
- [ ] Private eval sets (stored outside git, under `library/evals/`):
  - **Harry Potter:** about 30 cases aimed at the worst-case leaks (Scabbers,
    the Half-Blood Prince, Snape's loyalty, Horcruxes, R.A.B.).
  - **Cradle:** about 30 cases for usefulness and the power system.
- [ ] Eval runner: prints a leak rate, a "useful answer" score (a
  model-judged rubric plus your own spot checks), and citation validity.

**Gate:** the eval set exists and runs end to end against a stub answerer.

## Phase 1: Spoiler-safe baseline (≈2–3 weeks)

**EPUB → passages → search + rolling summaries → cited answers.** No knowledge graph yet.

- [ ] EPUB parser: spine order, **splitting an omnibus into its books** (from the
  nested TOC, with a manual override file), chapter detection (TOC + heading heuristics),
  stripping front and back matter, paragraph segmentation into passages of
  about 150–400 words, assigning `pos`.
- [ ] Indexing: full-text search (FTS5 or Postgres tsvector) plus embeddings.
- [ ] Hybrid retrieval filtered by `pos ≤ horizon`, enforced in the query
  layer. Callers cannot bypass it.
- [ ] Rolling chapter summaries (chapter N summary built from chapter N plus
  earlier summaries) and book recaps built from chapter summaries.
- [ ] Answerer: retrieve → answer only from context → check every citation
  against the horizon → drop unsupported sentences.
- [ ] CLI: `tome ingest book.epub --series X --order 1`,
  `tome ask --series X --at "b2 ch14" "who is Busoni?"`,
  `tome recap --series X --at "b2 ch1"`.
- [ ] Ingestion is resumable and checkpointed per chapter, and logs token
  counts and cost.
- [ ] Compare open-model sizes (about 8–14B vs about 70B) on a sample of about
  3 chapters first. Run the full corpus only on the smallest model that passes
  the evals.

**Gate:** leak rate is 0 on the hard check and near 0 on the soft check.
Answers are useful enough that you reach for them while reading. Record the
weak spots, which are likely aliases, "who is" for minor characters, and
history across books. Those weak spots justify Phase 2.

## Phase 2: Structured layer (≈3–4 weeks), only where the baseline is weak

- [ ] Mention extraction per chunk (structured JSON output): named
  characters, places, factions, objects, with a free-text `type`.
- [ ] **Incremental alias resolution in reading order**, with
  `established_at` on each alias link. Run it on the Monte Cristo reveals.
- [ ] Observations: `(subject, predicate, object|value, status ∈ {stated,
  claimed_by, inferred}, evidence_passage, pos, run_id)`.
- [ ] Entity profile at a given horizon: built from observations ≤ horizon,
  cached at chapter checkpoints with `max_source_pos`.
- [ ] "Who is X?" uses the entity profile + top mentions + first appearance.
- [ ] Compare against the Phase 1 baseline on the same eval set: a small
  local model vs a larger model. Keep a component only if it wins.

**Gate:** the structured layer clearly beats the baseline on "who is this"
and relationship questions. If it doesn't, ship the baseline and stop adding
structure.

## Phase 3: Something you can use while reading (≈2 weeks)

- [ ] Thin web API (FastAPI) and a **mobile-first web page / PWA**: series
  picker, a horizon bar that is always visible, ask box, recap button,
  answer → evidence → passage.
- [ ] Position capture: chapter picker, a "paste a sentence" fuzzy match, an
  iOS Shortcut / Android share target that sends selected text, and
  optionally screenshot OCR.
- [ ] "I finished a chapter" button. The horizon only moves forward when you
  choose to move it.
- [ ] Runs on a home machine. Reach it from your phone over Tailscale or
  similar. No public hosting needed.

**Gate:** you use it through one whole book of a real series.

## Phase 4: Friends beta (≈ongoing)

- [ ] Packaging: Docker Compose, or a single binary plus a SQLite file.
- [ ] Multiple users, each with their own horizon. Shared ingestion per
  series, because the same series only needs processing once.
- [ ] Feedback button on answers ("wrong", "spoiled me", "missing"). Every
  "spoiled me" becomes a new eval case.
- [ ] Mystery / unresolved-question tracking (first version).

## Phase 5: Decide on commercial direction

Use the author conversations (see [AUTHOR_OUTREACH.md](AUTHOR_OUTREACH.md))
and the beta experience to choose between staying personal, going open
source, or building an author-sanctioned companion pilot with one author.

---

## Things deliberately left out until there's evidence they're needed

Graph database, ontology engine, contradiction reconciliation, magic-system
modeling, maps, timeline UI, community editing, public wiki, native mobile
apps, and DRM handling of any kind.

## Resolved questions

Your answers to the original open questions (hardware, books, reading app,
cloud policy, storage) are recorded in [DECISIONS.md](DECISIONS.md).
