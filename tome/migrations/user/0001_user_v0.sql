-- user.sqlite schema v0: the reader's own data. Never part of a pack.

-- Packs the reader has imported. One row per series (pack_id is stable across
-- recompiles); importing a new pack version replaces the row.
CREATE TABLE library (
    pack_id            TEXT PRIMARY KEY,
    series_title       TEXT    NOT NULL,
    path               TEXT    NOT NULL,
    pack_version       INTEGER NOT NULL,
    schema_version     INTEGER NOT NULL,
    embedding_model_id TEXT,
    content_hash       TEXT,
    imported_at        TEXT    NOT NULL
);

-- The reader's horizon per series, stored as a stable anchor rather than an
-- integer pos, because pos can change when a series is recompiled.
--   fingerprint IS NULL  -> "I have finished chapter `chapter_number`"
--                           (chapter_number = 0 means "not started this book")
--   fingerprint NOT NULL -> "I am in the passage that starts with these words"
-- Resolution to a pos happens on every open and rounds backwards when the
-- match is uncertain (tome/horizon.py).
CREATE TABLE horizons (
    pack_id        TEXT PRIMARY KEY,
    book_number    INTEGER NOT NULL CHECK (book_number >= 1),
    chapter_number INTEGER NOT NULL CHECK (chapter_number >= 0),
    fingerprint    TEXT,
    set_via        TEXT    NOT NULL DEFAULT 'manual',  -- 'chapter_picker', 'share_text', ...
    updated_at     TEXT    NOT NULL
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
