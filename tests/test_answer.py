"""The baseline answerer's keyword fallback."""

import pytest

from tome.answer import answer
from tome.horizon import HorizonReader
from tome.pack_writer import BookText, ChapterText, PackWriter

PASSAGES = [
    "Dantès swam until a sailor of the tartan caught hold of his hair and pulled him aboard.",
    "The young sailor Dantès thanked the crew and took the helm.",
    "The purse held a receipt and a diamond, and a note signed Sinbad the Sailor.",
    "Morrel wept for joy in the street.",
]


@pytest.fixture
def pack(tmp_path):
    w = PackWriter(tmp_path / "p.tome", pack_id="t", series_title="T")
    w.add_book(1, BookText("B", [ChapterText(f"C{i}", [p]) for i, p in enumerate(PASSAGES)]))
    w.finalize()
    w.close()
    return tmp_path / "p.tome"


def test_fallback_prefers_passages_with_every_word(pack):
    with HorizonReader(pack, len(PASSAGES)) as r:
        shown = answer(r, "Who is Sinbad the Sailor?").text
    assert "Sinbad" in shown and "Dantès" not in shown


def test_fallback_still_matches_any_word_when_none_has_all(pack):
    with HorizonReader(pack, len(PASSAGES)) as r:
        shown = answer(r, "Why did Morrel weep at the harbour?").text
    assert "Morrel wept" in shown
