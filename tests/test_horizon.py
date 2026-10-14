"""The horizon layer must make post-horizon rows unreachable, whatever SQL is tried."""

import sqlite3

import pytest

from tome.horizon import (
    Anchor,
    HorizonError,
    HorizonReader,
    anchor_for_pos,
    resolve_anchor,
)
from tome.text import fingerprint

H = 4  # end of book 1 in the tiny pack; "early" rows are at pos 2, "late" at pos 7


@pytest.fixture
def reader(tiny_pack):
    with HorizonReader(tiny_pack, H) as r:
        yield r


TABLE_TEXT = {
    "h_observations": "sentence",
    "h_relationships": "description",
    "h_entity_profiles": "profile_text",
    "h_chapter_summaries": "summary_text",
    "h_rollups": "text",
    "h_anticipated_qa": "answer",
}


@pytest.mark.parametrize("view,col", TABLE_TEXT.items())
def test_views_only_return_rows_at_or_before_horizon(reader, view, col):
    values = [r[col] for r in reader.query(f"SELECT {col} FROM {view}")]
    assert values and all(v.startswith("early") for v in values)


def test_every_visible_row_respects_horizon(reader):
    views = [r[0] for r in reader.query("SELECT name FROM sqlite_temp_master WHERE type='view'")]
    assert len(views) >= 12
    for view in views:
        if view == "h_passages_fts":  # only usable with MATCH; covered below
            continue
        rows = reader.query(f"SELECT * FROM {view}")
        if not rows:
            continue
        cols = [
            c
            for c in ("max_source_pos", "established_at", "pos", "start_pos")
            if c in rows[0].keys()  # noqa: SIM118 (sqlite3.Row has no __contains__ for keys)
        ]
        assert cols, view
        for row in rows:
            assert all(row[c] <= H for c in cols), (view, dict(row))


BYPASS_ATTEMPTS = [
    "SELECT * FROM observations",
    "SELECT sentence FROM main.observations",
    "SELECT text FROM passages WHERE pos > 4",
    "SELECT * FROM entity_profiles",
    "SELECT count(*) FROM observations",
    "SELECT max(max_source_pos) FROM chapter_summaries",
    "SELECT text FROM passages_fts WHERE passages_fts MATCH 'secret'",
    "SELECT rowid FROM passages_fts WHERE passages_fts MATCH 'secret'",
    "SELECT * FROM passages_fts('secret')",
    "SELECT * FROM aliases",
    "SELECT * FROM entity_identities",
    "SELECT * FROM h_observations o JOIN observations o2 USING (observation_id)",
    "SELECT (SELECT sentence FROM observations LIMIT 1)",
    "WITH x AS (SELECT * FROM rollups) SELECT * FROM x",
    "CREATE TEMP VIEW sneaky AS SELECT * FROM observations",
    "CREATE TEMP TABLE sneaky AS SELECT * FROM observations",
    "DROP VIEW h_observations",
    "ATTACH DATABASE ':memory:' AS other",
    "PRAGMA writable_schema = 1",
    "INSERT INTO observations (sentence) VALUES ('x')",
    "UPDATE chapters SET start_pos = 0",
]


@pytest.mark.parametrize("sql", BYPASS_ATTEMPTS)
def test_direct_access_to_protected_tables_is_refused(reader, sql):
    with pytest.raises((HorizonError, sqlite3.DatabaseError)):
        reader.query(sql)


def test_cannot_redefine_horizon_views_after_open(reader):
    with pytest.raises((HorizonError, sqlite3.DatabaseError)):
        reader.query("CREATE TEMP VIEW h_x AS SELECT 1")
    assert reader.horizon == H
    with pytest.raises(AttributeError):
        reader.horizon = 99


def test_full_text_search_is_horizon_filtered(reader, tiny_pack):
    assert reader.search_passages("secret") == []  # the only match is at pos 7
    assert [p["pos"] for p in reader.search_passages("passage")] and all(
        p["pos"] <= H for p in reader.search_passages("passage", limit=50)
    )
    with HorizonReader(tiny_pack, 8) as late:
        assert [p["pos"] for p in late.search_passages("secret")] == [7]


def test_alias_reveal_is_hidden_until_established(reader, tiny_pack):
    assert reader.entities_for_name("Secret Name") == []
    assert len(reader.entities_for_name("The Stranger")) == 1
    early = reader.entities_for_name("The Stranger")[0]["entity_id"]
    assert reader.identities(early) == []
    with HorizonReader(tiny_pack, 7) as late:
        assert len(late.entities_for_name("Secret Name")) == 2
        assert late.identities(early) != []


def test_horizon_zero_sees_nothing(tiny_pack):
    with HorizonReader(tiny_pack, 0) as r:
        assert r.query("SELECT * FROM h_passages") == []
        assert r.query("SELECT * FROM h_chapters") == []
        assert r.books()  # public metadata stays readable
        assert r.manifest()["pack_id"] == "tiny"


@pytest.mark.parametrize("bad", [-1, 1.5, "4", None, True])
def test_horizon_must_be_a_non_negative_int(tiny_pack, bad):
    with pytest.raises(HorizonError):
        HorizonReader(tiny_pack, bad)


def test_pack_is_opened_read_only(tiny_pack, reader):
    with pytest.raises((HorizonError, sqlite3.DatabaseError)):
        reader.query("DELETE FROM manifest")


def test_reader_helpers_respect_horizon(reader):
    early = reader.entities_for_name("The Stranger")[0]["entity_id"]
    assert reader.latest_profile(early)["profile_text"] == "early profile"
    assert [o["sentence"] for o in reader.observations(early)] == ["early observation"]
    assert [r["description"] for r in reader.relationships(early)] == ["early relationship"]
    assert reader.latest_rollup()["text"] == "early rollup"
    assert [s["summary_text"] for s in reader.chapter_summaries()] == ["early summary"]
    assert [q["answer"] for q in reader.anticipated_qa()] == ["early answer"]
    assert all(c["start_pos"] <= H for c in reader.chapters())


# ------------------------------------------------------------------- anchors --


def test_anchor_parse():
    assert Anchor.parse("b3 ch10") == Anchor(3, 10)
    assert Anchor.parse("Book 2, Chapter 1") == Anchor(2, 1)
    with pytest.raises(ValueError):
        Anchor.parse("chapter ten")


def test_finished_chapter_resolves_to_chapter_end(tiny_pack):
    assert resolve_anchor(tiny_pack, Anchor(1, 1)).pos == 2
    assert resolve_anchor(tiny_pack, Anchor(2, 2)).pos == 8
    assert resolve_anchor(tiny_pack, Anchor(2, 0)).pos == 4  # not started book 2


def test_in_passage_resolves_to_just_before_it(tiny_pack):
    text = "Book 2 chapter 1 passage 2 " + " ".join(f"w{i}" for i in range(20))
    res = resolve_anchor(tiny_pack, Anchor(2, 1, fingerprint(text)))
    assert res.exact and res.pos == 5  # passage 2 of b2c1 is pos 6


def test_uncertain_anchors_round_backwards(tiny_pack):
    unknown = resolve_anchor(tiny_pack, Anchor(2, 2, "words that match nothing at all here"))
    assert not unknown.exact and unknown.pos == 6  # start of b2 ch2, minus one
    missing_ch = resolve_anchor(tiny_pack, Anchor(2, 9))
    assert not missing_ch.exact and missing_ch.pos == 8 - 0  # last chapter < 9 ends at 8
    missing_book = resolve_anchor(tiny_pack, Anchor(5, 1))
    assert not missing_book.exact and missing_book.pos == 8
    assert resolve_anchor(tiny_pack, Anchor(1, 7)).pos == 4


def test_fingerprint_prefix_tolerates_edition_drift(tiny_pack):
    # Same opening words, but the reader's edition has a longer first sentence.
    res = resolve_anchor(tiny_pack, Anchor(1, 2, "book 1 chapter 2 passage 2 w0 w1 w2 w3 w4 w5 w6"))
    assert res.pos == 3 and not res.exact


@pytest.mark.parametrize("pos", range(0, 9))
def test_anchor_round_trip(tiny_pack, pos):
    anchor = anchor_for_pos(tiny_pack, pos) if pos else Anchor(1, 0)
    assert resolve_anchor(tiny_pack, anchor).pos == pos
