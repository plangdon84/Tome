-- Series pack schema v0.
--
-- A pack is one SQLite file per series, written by the compiler at ingestion
-- and opened read-only at reading time.
--
-- Invariants enforced here:
--   * One integer `pos` axis: every passage has a unique, monotonic `pos`
--     across the whole series (starting at 1). A horizon is a `pos`.
--   * Every derived table has `max_source_pos` (the furthest `pos` of any
--     input used to build the row) and `run_id`. A derived row is visible only
--     when `max_source_pos <= horizon` (plus `pos` / `established_at` where
--     those columns exist). Filtering happens in tome/horizon.py, the only
--     reader of these tables.
--   * Quote or drop: an observation can only be stored if its quote span is a
--     verbatim substring of its evidence passage and the passage `pos` equals
--     the observation `pos` (trigger below).

-- ---------------------------------------------------------------- public ----
-- Tables in this section are readable without a horizon.

CREATE TABLE manifest (
    singleton          INTEGER PRIMARY KEY CHECK (singleton = 1),
    pack_id            TEXT    NOT NULL,   -- stable series id, e.g. "monte-cristo"
    series_title       TEXT    NOT NULL,
    pack_version       INTEGER NOT NULL,   -- bumped on every recompile
    schema_version     INTEGER NOT NULL,   -- = PRAGMA user_version when compiled
    compiler_version   TEXT    NOT NULL,
    llm_model          TEXT,               -- NULL for a parse-only pack
    embedding_model_id TEXT,               -- must match the app's embedder
    content_hash       TEXT,               -- sha256 over passages, see pack_writer
    compiled_at        TEXT    NOT NULL    -- ISO-8601 UTC
);

-- Book titles and order are treated as public: the reader picks a book from
-- this list before any horizon exists.
CREATE TABLE books (
    book_id       INTEGER PRIMARY KEY,
    number        INTEGER NOT NULL UNIQUE,  -- reading order, 1-based
    title         TEXT    NOT NULL,
    start_pos     INTEGER NOT NULL,
    end_pos       INTEGER NOT NULL,
    source_file   TEXT,                     -- file name only, never a full path
    source_sha256 TEXT,
    CHECK (end_pos >= start_pos)
);

-- Provenance for every derived row. One row per compiler run (a pass with one
-- model and prompt version).
CREATE TABLE runs (
    run_id            INTEGER PRIMARY KEY,
    kind              TEXT NOT NULL,        -- 'parse', 'summaries', 'extract', 'stub', ...
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    compiler_version  TEXT NOT NULL,
    llm_provider      TEXT,
    llm_model         TEXT,
    prompt_version    TEXT,
    params_json       TEXT NOT NULL DEFAULT '{}',
    -- e.g. {"quote_candidates": 120, "quote_dropped": 7}
    stats_json        TEXT NOT NULL DEFAULT '{}',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL
);

-- ------------------------------------------------------------ source text ---
-- Source text and its structure. Not derived by an LLM, but still horizon
-- filtered: chapter titles and passage text after the horizon are spoilers.

CREATE TABLE chapters (
    chapter_id INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(book_id),
    number     INTEGER NOT NULL,   -- 1-based ordinal within the book
    title      TEXT    NOT NULL,
    start_pos  INTEGER NOT NULL,
    end_pos    INTEGER NOT NULL,
    UNIQUE (book_id, number),
    CHECK (end_pos >= start_pos)
);

CREATE TABLE passages (
    passage_id  INTEGER PRIMARY KEY,
    chapter_id  INTEGER NOT NULL REFERENCES chapters(chapter_id),
    pos         INTEGER NOT NULL UNIQUE CHECK (pos >= 1),
    seq         INTEGER NOT NULL,  -- 0-based index within the chapter
    text        TEXT    NOT NULL,
    word_count  INTEGER NOT NULL,
    fingerprint TEXT    NOT NULL,  -- normalised first words, for horizon anchors
    UNIQUE (chapter_id, seq)
);
CREATE INDEX passages_chapter ON passages(chapter_id, seq);

-- External-content FTS5 index over passages. Kept in sync by the writer
-- (packs are built once and then never modified).
CREATE VIRTUAL TABLE passages_fts USING fts5(
    text,
    content = 'passages',
    content_rowid = 'passage_id',
    tokenize = 'unicode61 remove_diacritics 2'
);

-- --------------------------------------------------------------- derived ----
-- Everything below is compiler output. Every table has max_source_pos and
-- run_id, both NOT NULL.

CREATE TABLE entities (
    entity_id       INTEGER PRIMARY KEY,
    kind            TEXT    NOT NULL,           -- free text: 'person', 'place', ...
    first_pos       INTEGER NOT NULL,
    attributes_json TEXT    NOT NULL DEFAULT '{}',
    max_source_pos  INTEGER NOT NULL,
    run_id          INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= first_pos)
);

-- Surface form -> entity. `established_at` is the pos where the text makes
-- this link knowable. Before that, the name belongs to someone else (or no
-- one) as far as the reader is concerned.
CREATE TABLE aliases (
    alias_id            INTEGER PRIMARY KEY,
    entity_id           INTEGER NOT NULL REFERENCES entities(entity_id),
    surface_form        TEXT    NOT NULL,
    normalized          TEXT    NOT NULL,       -- lower-cased, accents stripped
    established_at      INTEGER NOT NULL,
    evidence_passage_id INTEGER REFERENCES passages(passage_id),
    max_source_pos      INTEGER NOT NULL,
    run_id              INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= established_at)
);
CREATE INDEX aliases_normalized ON aliases(normalized);

-- Identity reveals between two entities that the reader first meets as
-- separate people (Abbé Busoni -> Edmond Dantès, Scabbers -> Pettigrew).
CREATE TABLE entity_identities (
    identity_id         INTEGER PRIMARY KEY,
    entity_id           INTEGER NOT NULL REFERENCES entities(entity_id),
    same_as_entity_id   INTEGER NOT NULL REFERENCES entities(entity_id),
    established_at      INTEGER NOT NULL,
    evidence_passage_id INTEGER REFERENCES passages(passage_id),
    max_source_pos      INTEGER NOT NULL,
    run_id              INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= established_at),
    CHECK (entity_id <> same_as_entity_id)
);

CREATE TABLE mentions (
    mention_id     INTEGER PRIMARY KEY,
    passage_id     INTEGER NOT NULL REFERENCES passages(passage_id),
    entity_id      INTEGER NOT NULL REFERENCES entities(entity_id),
    surface_form   TEXT    NOT NULL,
    pos            INTEGER NOT NULL,
    max_source_pos INTEGER NOT NULL,
    run_id         INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= pos)
);

CREATE TABLE observations (
    observation_id       INTEGER PRIMARY KEY,
    sentence             TEXT    NOT NULL,       -- ready-to-show natural language
    subject_entity_id    INTEGER NOT NULL REFERENCES entities(entity_id),
    predicate            TEXT    NOT NULL,       -- free text
    object_entity_id     INTEGER REFERENCES entities(entity_id),
    object_text          TEXT,
    status               TEXT    NOT NULL CHECK (status IN ('stated', 'claimed', 'inferred')),
    claimed_by_entity_id INTEGER REFERENCES entities(entity_id),
    evidence_passage_id  INTEGER NOT NULL REFERENCES passages(passage_id),
    quote_span           TEXT    NOT NULL CHECK (length(quote_span) > 0),
    quote_start          INTEGER NOT NULL,       -- 0-based char offsets into passage text
    quote_end            INTEGER NOT NULL,
    pos                  INTEGER NOT NULL,
    max_source_pos       INTEGER NOT NULL,
    run_id               INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= pos),
    CHECK (quote_end > quote_start),
    CHECK (status <> 'claimed' OR claimed_by_entity_id IS NOT NULL)
);
CREATE INDEX observations_subject ON observations(subject_entity_id, pos);

CREATE TRIGGER observations_quote_or_drop_insert
BEFORE INSERT ON observations
WHEN NOT EXISTS (
    SELECT 1 FROM passages p
    WHERE p.passage_id = NEW.evidence_passage_id
      AND p.pos = NEW.pos
      AND substr(p.text, NEW.quote_start + 1, NEW.quote_end - NEW.quote_start) = NEW.quote_span
)
BEGIN
    SELECT RAISE(ABORT, 'quote-or-drop: quote_span is not verbatim in the evidence passage at pos');
END;

CREATE TRIGGER observations_quote_or_drop_update
BEFORE UPDATE ON observations
WHEN NOT EXISTS (
    SELECT 1 FROM passages p
    WHERE p.passage_id = NEW.evidence_passage_id
      AND p.pos = NEW.pos
      AND substr(p.text, NEW.quote_start + 1, NEW.quote_end - NEW.quote_start) = NEW.quote_span
)
BEGIN
    SELECT RAISE(ABORT, 'quote-or-drop: quote_span is not verbatim in the evidence passage at pos');
END;

CREATE TABLE relationships (
    relationship_id     INTEGER PRIMARY KEY,
    source_entity_id    INTEGER NOT NULL REFERENCES entities(entity_id),
    target_entity_id    INTEGER NOT NULL REFERENCES entities(entity_id),
    rel_type            TEXT    NOT NULL,        -- free text
    description         TEXT    NOT NULL,
    evidence_passage_id INTEGER REFERENCES passages(passage_id),
    pos                 INTEGER NOT NULL,
    max_source_pos      INTEGER NOT NULL,
    run_id              INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos >= pos)
);

-- "What you know about X so far", regenerated at checkpoints (chapter ends
-- where X gets new observations) from the previous profile plus new
-- observations.
CREATE TABLE entity_profiles (
    profile_id      INTEGER PRIMARY KEY,
    entity_id       INTEGER NOT NULL REFERENCES entities(entity_id),
    checkpoint_pos  INTEGER NOT NULL,
    display_name    TEXT    NOT NULL,
    profile_text    TEXT    NOT NULL,
    prev_profile_id INTEGER REFERENCES entity_profiles(profile_id),
    max_source_pos  INTEGER NOT NULL,
    run_id          INTEGER NOT NULL REFERENCES runs(run_id),
    CHECK (max_source_pos <= checkpoint_pos)
);
CREATE INDEX entity_profiles_entity ON entity_profiles(entity_id, max_source_pos);

CREATE TABLE chapter_summaries (
    summary_id     INTEGER PRIMARY KEY,
    chapter_id     INTEGER NOT NULL REFERENCES chapters(chapter_id),
    summary_text   TEXT    NOT NULL,
    max_source_pos INTEGER NOT NULL,
    run_id         INTEGER NOT NULL REFERENCES runs(run_id)
);

-- Book recaps and "story so far" rollups at checkpoints.
CREATE TABLE rollups (
    rollup_id          INTEGER PRIMARY KEY,
    kind               TEXT    NOT NULL CHECK (kind IN ('book', 'story_so_far')),
    book_id            INTEGER REFERENCES books(book_id),
    through_chapter_id INTEGER REFERENCES chapters(chapter_id),
    text               TEXT    NOT NULL,
    max_source_pos     INTEGER NOT NULL,
    run_id             INTEGER NOT NULL REFERENCES runs(run_id)
);

-- Questions a reader is likely to have at a chapter, answered only from text
-- up to that point.
CREATE TABLE anticipated_qa (
    qa_id                 INTEGER PRIMARY KEY,
    chapter_id            INTEGER NOT NULL REFERENCES chapters(chapter_id),
    question              TEXT    NOT NULL,
    answer                TEXT    NOT NULL,
    evidence_passage_ids  TEXT    NOT NULL DEFAULT '[]',  -- JSON array of passage_id
    max_source_pos        INTEGER NOT NULL,
    run_id                INTEGER NOT NULL REFERENCES runs(run_id)
);

-- Vectors from the pinned embedding model (manifest.embedding_model_id).
CREATE TABLE embeddings (
    embedding_id   INTEGER PRIMARY KEY,
    owner_table    TEXT    NOT NULL,  -- 'passages', 'observations', 'anticipated_qa', ...
    owner_id       INTEGER NOT NULL,
    model_id       TEXT    NOT NULL,
    dim            INTEGER NOT NULL,
    vector         BLOB    NOT NULL,  -- little-endian float32
    max_source_pos INTEGER NOT NULL,
    run_id         INTEGER NOT NULL REFERENCES runs(run_id),
    UNIQUE (owner_table, owner_id, model_id)
);
