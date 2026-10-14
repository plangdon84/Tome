import sqlite3

import pytest

from tome.db import _split_sql, connect_rw, latest_version, migrations
from tome.horizon import HORIZON_COLUMNS, PUBLIC_TABLES

DERIVED = {
    "entities",
    "aliases",
    "entity_identities",
    "mentions",
    "observations",
    "relationships",
    "entity_profiles",
    "chapter_summaries",
    "rollups",
    "anticipated_qa",
    "embeddings",
}


def table_columns(conn):
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " AND name NOT LIKE 'passages_fts%'"
        )
    ]
    return {t: {r[1]: r for r in conn.execute(f"PRAGMA table_info({t})")} for t in tables}


def test_pack_migration_creates_expected_tables(tmp_path):
    conn = connect_rw(tmp_path / "p.tome", "pack")
    cols = table_columns(conn)
    assert cols.keys() >= DERIVED
    assert {"manifest", "books", "chapters", "passages", "runs"} <= cols.keys()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_version("pack")
    manifest = set(cols["manifest"])
    assert {
        "pack_id",
        "series_title",
        "pack_version",
        "schema_version",
        "compiler_version",
        "llm_model",
        "embedding_model_id",
        "content_hash",
        "compiled_at",
    } <= manifest


def test_every_derived_table_has_max_source_pos_and_run_id(tmp_path):
    conn = connect_rw(tmp_path / "p.tome", "pack")
    for table, cols in table_columns(conn).items():
        if table in DERIVED:
            for col in ("max_source_pos", "run_id"):
                assert col in cols, f"{table} lacks {col}"
                assert cols[col][3] == 1, f"{table}.{col} must be NOT NULL"


def test_every_non_public_table_is_horizon_filterable(tmp_path):
    """New tables must either be public or carry a horizon column."""
    conn = connect_rw(tmp_path / "p.tome", "pack")
    for table, cols in table_columns(conn).items():
        if table not in PUBLIC_TABLES:
            assert any(c in cols for c in HORIZON_COLUMNS), table


def test_user_db_schema(tmp_path):
    conn = connect_rw(tmp_path / "user.sqlite", "user")
    cols = table_columns(conn)
    assert {"book_number", "chapter_number", "fingerprint"} <= set(cols["horizons"])
    assert "library" in cols


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "p.tome"
    connect_rw(path, "pack").close()
    conn = connect_rw(path, "pack")  # second run applies nothing
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(migrations("pack"))


def test_split_sql_keeps_trigger_bodies_whole():
    sql = migrations("pack")[0][2]
    statements = _split_sql(sql)
    triggers = [s for s in statements if s.startswith("CREATE TRIGGER")]
    assert len(triggers) == 2 and all(s.rstrip().endswith("END;") for s in triggers)


def test_quote_or_drop_trigger_rejects_bad_quote(tiny_pack):
    conn = sqlite3.connect(tiny_pack)
    row = conn.execute("SELECT passage_id, pos FROM passages WHERE pos=3").fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="quote-or-drop"):
        conn.execute(
            "INSERT INTO observations (sentence, subject_entity_id, predicate, status,"
            " evidence_passage_id, quote_span, quote_start, quote_end, pos, max_source_pos,"
            " run_id) VALUES ('s', 1, 'p', 'stated', ?, 'not in the passage', 0, 18, ?, ?, 1)",
            (row[0], row[1], row[1]),
        )
    # Right text but wrong pos is rejected too.
    with pytest.raises(sqlite3.IntegrityError, match="quote-or-drop"):
        conn.execute(
            "INSERT INTO observations (sentence, subject_entity_id, predicate, status,"
            " evidence_passage_id, quote_span, quote_start, quote_end, pos, max_source_pos,"
            " run_id) VALUES ('s', 1, 'p', 'stated', ?, 'Book 1', 0, 6, 1, 1, 1)",
            (row[0],),
        )
