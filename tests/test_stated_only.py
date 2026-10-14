"""Default posture: answers show what the text has stated; inferences only on request."""

import sqlite3

import pytest

from tome.answer import answer, is_speculative
from tome.horizon import Anchor, HorizonReader, resolve_anchor
from tome.pack_writer import BookText, ChapterText, PackWriter


@pytest.mark.parametrize(
    "q,spec",
    [
        ("Who is Sinbad the Sailor?", False),
        ("Who might Sinbad the Sailor be?", True),
        ("Any theories about the priest?", True),
        ("Could the priest be Dantès?", True),
        ("What clues are there about Sinbad?", True),
        ("What happened at the Château d'If?", False),
    ],
)
def test_speculative_questions(q, spec):
    assert is_speculative(q) is spec


def at(pack, chapter):
    return HorizonReader(pack, resolve_anchor(pack, Anchor(1, chapter)).pos)


def test_inference_hidden_by_default_shown_when_asked(stub_pack):
    with at(stub_pack, 30) as r:
        plain = answer(r, "Who is Sinbad the Sailor?").text
        asked = answer(r, "Who might Sinbad the Sailor be?").text
    assert "Dantès" not in plain
    assert "may be Edmond Dantès" in asked and "not confirmed" in asked


def test_inferred_identity_was_not_stored(stub_pack):
    """The stub's Sinbad = Dantès link (ch 30) had no stating quote: dropped."""
    with at(stub_pack, 117) as r:
        sinbad = r.entities_for_name("Sinbad the Sailor")[0]["entity_id"]
        dantes = r.entities_for_name("Edmond Dantès")[0]["entity_id"]
        assert dantes not in r.identities(sinbad)  # only via the Count, stated later


def test_claims_are_attributed(stub_pack, monkeypatch):
    with at(stub_pack, 66) as r:
        # Without a profile, observations are listed one by one.
        monkeypatch.setattr(r, "latest_profile", lambda entity_id: None)
        text = answer(r, "Who is the Abbé Busoni?").text
    assert "(Count of Monte Cristo claims) The count says the Abbé Busoni is his friend." in text


def test_trigger_refuses_identity_without_stating_quote(tiny_pack):
    conn = sqlite3.connect(tiny_pack)
    pid = conn.execute("SELECT passage_id FROM passages WHERE pos=7").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="stated-reveal"):
        conn.execute(
            "INSERT INTO entity_identities (entity_id, same_as_entity_id, established_at,"
            " evidence_passage_id, max_source_pos, run_id) VALUES (1, 2, 7, ?, 7, 1)",
            (pid,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="stated-reveal"):
        conn.execute(  # quote is real but from a different pos than established_at
            "INSERT INTO entity_identities (entity_id, same_as_entity_id, established_at,"
            " evidence_passage_id, quote_span, quote_start, quote_end, max_source_pos, run_id)"
            " VALUES (1, 2, 8, ?, 'Book 2', 0, 6, 8, 1)",
            (pid,),
        )


def test_writer_drops_identity_whose_quote_is_not_in_the_passage(tmp_path):
    w = PackWriter(tmp_path / "p.tome", pack_id="p", series_title="P")
    w.add_book(1, BookText("B", [ChapterText("c", ["The priest asked about the young sailor."])]))
    run = w.start_run("t")
    a = w.add_entity(kind="person", first_pos=1, run_id=run)
    b = w.add_entity(kind="person", first_pos=1, run_id=run)
    pid = w.passage_at(1)["passage_id"]
    assert (
        w.add_identity(
            entity_id=a,
            same_as_entity_id=b,
            evidence_passage_id=pid,
            quote="the priest is really Dantès",
            run_id=run,
        )
        is None
    )
    assert (
        w.add_identity(
            entity_id=a,
            same_as_entity_id=b,
            evidence_passage_id=pid,
            quote="The priest asked about",
            run_id=run,
        )
        is not None
    )
    assert w.quote_stats[run].candidates == 2 and w.quote_stats[run].dropped == 1
