# Architecture: LLM at ingestion, no LLM at reading time

## The principle

> **The LLM is a compiler, not a chatbot.** It runs once per book, in batch,
> on rented hardware, and compiles the book into a **knowledge database**.
> The companion app answers every question **from that database alone**.
> No LLM is called at reading time.

```
                 INGESTION  (once per book, rented GPU, open-weight LLM)
EPUB ─▶ parse ─▶ passages ─▶ LLM passes, in reading order ─▶ tome.sqlite
                                                                │
                                                     copied to the device
                                                                ▼
                 READING TIME  (in the app, offline, no LLM)
question ─▶ query understanding ─▶ horizon-filtered lookups + semantic search
         ─▶ answer assembled from precomputed text ─▶ evidence ─▶ passage
```

## Consequences

**Good:**
- **No leaks from the model's own memory at reading time.** The only text a
  reader ever sees was written at ingestion and is tagged with a position.
  All spoiler risk is concentrated in one place (ingestion), where it can be
  audited offline and in bulk, before anyone reads it.
- **Spoiler safety becomes deterministic.** Every answer is a filtered lookup:
  `max_source_pos ≤ horizon`. No prompt can trick it.
- **Fully offline and private at reading time.** No server and no API key.
  No Mac has to be awake.
- **Cost at reading time is zero.** Answers are instant.
- **The database is the product.** A future wiki is just another view of the
  same database.

**Costs:**
- **Answers can only be as good as what was precomputed.** The app can find,
  rank, filter, and assemble. It cannot reason about a question nobody
  anticipated. A question like "why did X really leave the Order?" works only
  if ingestion stored an observation or anticipated Q&A that covers it.
- **This makes the structured layer central.** It is no longer an optional
  Phase 2. The viability test is now: *"Does the compiled database answer the
  questions real readers actually ask?"*
- **Ingestion does more work** (profiles at checkpoints, anticipated
  questions), so it costs more GPU time. That's fine, because it's batch work.

## What ingestion produces (the data products)

Every row carries `pos` / `max_source_pos` and `run_id`.

| Product | What it is | Answers |
|---|---|---|
| **Passages** | The source text, split into chunks of about 150–400 words, each with a `pos`. Includes FTS5 and embeddings. | Evidence display, "where have I seen this?", fallback search |
| **Mentions + alias links** | Each surface form → entity. Each alias link has `established_at`. | Resolving names in the question. Identity reveals stay hidden. |
| **Observations** | Short, **natural-language** atomic statements written by the LLM, plus structured fields: `(subject, predicate, object, status, evidence_passage, quote_span, pos)`. Example: *"Ron says Scabbers has been in his family for twelve years."* (claimed_by: Ron). | Assembling answers. Each observation is a ready-to-show sentence. |
| **Identity reveals** | "X is Y" links, only where the text **states** it, with a verbatim quote from the reveal passage (see DECISIONS.md §9). | Resolving names once a reveal has happened. |
| **Entity profiles at checkpoints** | A short "what you know about X so far". Regenerated only at chapters where X gets new observations. Built from the previous profile plus new observations, so it is incremental and safe by construction. | "Who is X?" |
| **Relationships** | Typed edges (free-text type) between entities, each with a `pos`. | "How are X and Y connected?" |
| **Chapter summaries** | One per chapter, built in rolling order, plus book recaps. Also "story so far" rollups at checkpoints. | "Recap", "what happened last book?" |
| **Anticipated Q&A** | At each chapter, the LLM writes questions a reader is likely to have at that point, with answers built *only* from text up to that point, and cited. | Free-form questions, matched by meaning |
| **Open questions** (later) | Mysteries raised by the text up to `pos`. Each is marked resolved at `resolved_pos`. | "What's still unresolved?" |
| **Embeddings** | Vectors for passages, observations, summaries, and anticipated questions, from **one small embedding model** that also runs on the device. | Semantic search |

### Auditing ingestion (where spoiler risk now lives)

- **Stated, not inferred (DECISIONS.md §9):** default answers use `stated`
  and attributed `claimed` facts only. `inferred` observations appear only for
  speculative questions, and identity reveals must be stated and quoted.
- **Quote check (mechanical):** every observation must include a verbatim quote
  span. The span must exist in its evidence passage, and the passage `pos` must
  equal the observation `pos`. Observations that fail are dropped. This
  catches the LLM "remembering" Harry Potter instead of reading it.
- **Profile and summary support check:** a second pass flags sentences in
  profiles and summaries that aren't supported by their inputs. This can run
  with an LLM, because it happens at ingestion. Flagged sentences are removed
  or regenerated.
- **The spoiler eval set runs against the database itself.** It needs no
  answerer at all.

## Reading time: answering with no LLM

The pipeline runs inside the app, on the device:

1. **Fix the horizon.** Every later step queries only rows where
   `pos ≤ horizon` (or `max_source_pos ≤ horizon`). This is enforced in a
   single data-access layer.
2. **Find entities in the question.** Match the question against the alias
   dictionary, **filtered by `established_at ≤ horizon`**. At HP Book 3 ch. 10,
   "Scabbers" and "Peter Pettigrew" are still separate entities, so asking
   about one never surfaces the other.
3. **Identify the question type**, using rules, keywords, and embedding
   similarity to example questions for each type:
   - *who/what is X* → profile at the latest checkpoint ≤ horizon, plus
     observations since that checkpoint, plus first appearance
   - *X and Y* → relationship edges and shared observations
   - *recap / last book / since chapter N* → chapter summaries and rollups
   - *where/when did …* → observation and passage search
   - *anything else* → semantic search across anticipated Q&A, observations,
     summaries, and passages, using combined keyword and meaning matching,
     with an optional small reranking model
4. **Build the answer** from the text that was precomputed: the best-matching
   anticipated answer, or a profile plus bullet points of observations. Each
   piece links to its evidence, and each piece of evidence links to its
   passage.
5. **Be honest about gaps.** If nothing scores above a threshold, show the
   best search results as "Possibly relevant passages". Never make anything
   up.

### Optional later: a small on-device model to rephrase answers

On-device models (for example, Apple's on-device foundation models on
supported iPhones, or a small model running in the browser) could *rephrase*
the retrieved, horizon-filtered snippets into smoother prose. That still
keeps everything inside the app. It is not needed for viability, and the
answer must stay limited to the retrieved snippets.

## Running inside the app: deployment shape

- **Database:** one SQLite file. Rough size estimate for both POC series:
  - about 15 MB of text
  - about 10–25 MB of embeddings (int8 or float32, 384-dim)
  - a few MB of observations, profiles, and summaries
  - **under about 100 MB in total**
- **App:** a **PWA** (an installable web app) that runs entirely in the
  browser.
  - SQLite runs in the browser, via SQLite-WASM or wa-sqlite with OPFS
    storage.
  - The small embedding model runs in the browser via ONNX / transformers.js.
  - This gives an offline app on the phone with no server and no Mac to keep
    awake.
- **Mac CLI:** a command-line version that uses the same query logic, for
  development and evals. Use Python first, and port the query layer to
  TypeScript for the PWA once the database schema settles. Alternatively,
  keep query logic thin and mostly in SQL so both are easy.
- **Embedding model:** must be identical at ingestion and at query time.
  Choose one small enough for the browser, e.g. a MiniLM, bge-small, or
  gte-small class model of about 20–35M parameters.
- **Note on sharing with friends:** the database contains book text (for
  evidence). Share it only with friends who own the books. Later, the app
  could rebuild the passages from each user's own EPUB and ship only the
  derived data.

## Series packs: one app, many series

**One app, and one database file per series** (a "series pack"). The app
keeps a library of packs. You don't need a separate app for each series.

```
App (one install)
├── user.sqlite            ← your data: library list, horizon per series, settings
├── packs/
│   ├── harry-potter.tome  ← SQLite, read-only, compiled at ingestion
│   ├── cradle.tome
│   └── monte-cristo.tome
└── embedding model        ← one model, shared by all packs
```

### Why one file per series

- **Content and your data are kept apart.** Packs are read-only compiler
  output. Your reading positions live in `user.sqlite`. Replacing a pack never
  touches your progress.
- **Packs can be replaced.** When a new book comes out or a better model
  recompiles a series, you swap in the new pack.
- **Packs are portable.** Import one via the file picker, the share sheet, or
  a download link. Hand one to a friend who owns the books. Delete one to free
  space.
- **Isolation is a safety net.** A question asked in one series can never pull
  in text from another.
- **The app opens one pack at a time**, the series you're currently asking
  about. Searching across series is rarely wanted. If it ever is, SQLite can
  attach several files at once.

### The pack manifest

Each pack has a manifest table that the app checks when you import it:

| Field | Purpose |
|---|---|
| `pack_id`, `series_title`, `books[]` | Library display, reading order |
| `pack_version`, `compiled_at`, `compiler_version`, `llm_model` | Provenance; deciding whether a pack should be upgraded |
| `schema_version` | The app refuses packs it can't read, or migrates them |
| `embedding_model_id` | **Must match the app's embedding model.** If it doesn't, the pack can't be searched by meaning, so the app warns you or falls back to keyword search. |
| `content_hash` | Integrity check; tells the app when two packs are the same |

### A horizon that survives recompiles

The integer `pos` may change when a series is re-parsed or recompiled. So
`user.sqlite` stores your horizon as a **stable anchor** made of three parts:
- the book number;
- the chapter number;
- the first words of the passage you were at, as a text fingerprint.

Every time the app opens a pack, it converts that anchor back into a `pos`. If
the match is uncertain, it rounds backward (invariant 6).

### Adding books to a series that's still being written

Ingestion runs in reading order, so compiling book N+1 needs only the stored
state from books 1–N:
- the alias table;
- the latest entity profiles;
- the summaries so far.

Positions in earlier books never change. The compiler produces a new pack
version with the new book appended, and you import it over the old one.

### Shared universes (later)

Some readers follow several connected series in one fictional universe, such
as Sanderson's Cosmere. These can be compiled into a single **universe pack**
with an explicit reading order, which defines a single `pos` axis across the
series. The same pack format handles this; it's just a larger pack.

### Storage on the phone

- Each pack is roughly 20–60 MB (HP and Cradle together come to under about
  100 MB).
- The PWA stores packs in the browser's private file storage (OPFS). It
  calls `navigator.storage.persist()` so iOS is less likely to delete them
  under storage pressure.
- Keep the original pack files on your Mac or in cloud storage, so you can
  re-import them after a phone reset.

## The viability test, restated

The POC passes when, on Harry Potter and Cradle:

1. **Coverage.** A large share of **real reader questions** is answered well
   from the database. Collect these questions as you read: write down
   whatever you actually wonder about.
2. **Safety.** Zero leaks on the spoiler eval set, checked against the
   database lookups.
3. **Fidelity.** The quote check passes for the vast majority of observations,
   and spot checks of profiles and summaries find them accurate.
4. **Model size.** The smallest open model that meets 1–3 is affordable to
   run.

If coverage falls short, the levers are, in order:

1. better anticipated Q&A
2. denser observations
3. better query routing
4. *(last resort)* an optional on-device model for rephrasing

A cloud LLM at reading time is **not** a lever.
