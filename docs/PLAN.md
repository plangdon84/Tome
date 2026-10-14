# Plan: From Zero to a Reading Companion You Use

This plan follows on from [REVIEW.md](REVIEW.md). The guiding idea is to
**build the cheapest spoiler-safe baseline first, measure it, and add
structure only where it measurably helps.**

Each phase ends with a decision gate: continue, change course, or stop.

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
  endpoint) and one `Embedder` interface. Config picks Ollama, local
  llama.cpp, or a cloud API.
- [ ] Download the public-domain corpus: *The Count of Monte Cristo* plus one
  multi-book series (Barsoom or Oz).
- [ ] **Spoiler eval set**, written by hand, about 40–60 cases:
  `{horizon, question, must_include[], must_not_include[]}`.
  Example: horizon = Monte Cristo ch. 30; Q: "Who is the Abbé Busoni?";
  must_not_include: "Dantès".
- [ ] A second, small private eval set on a series you know well and own as
  an EPUB (stored outside git), so results reflect the real use case.
- [ ] Eval runner: prints a leak rate, a "useful answer" score (a
  model-judged rubric plus your own spot checks), and citation validity.

**Gate:** the eval set exists and runs end to end against a stub answerer.

## Phase 1: Spoiler-safe baseline (≈2–3 weeks)

**EPUB → passages → search + rolling summaries → cited answers.** No knowledge graph yet.

- [ ] EPUB parser: spine order, chapter detection (TOC + heading heuristics),
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
  counts and time so you get **real compute numbers for your hardware**.

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

## Open questions for you

1. **Hardware:** what GPU, CPU, and RAM do you have, or do you have an
   M-series Mac? This decides local vs rented GPU vs API for ingestion.
2. **First real series:** which series do you most want this for, and do you
   own DRM-free EPUBs of it?
3. **Reading setup:** Kindle app, Apple Books, Kobo, or e-ink? This decides
   which position-capture method to build first.
4. **Cloud models:** are you OK using a no-training, no-retention API for
   ingestion of your own books during development, or strictly local?
5. **Storage:** SQLite (simplest, single file) or Postgres (as originally
   planned)?
