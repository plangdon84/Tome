import pytest

from tome.horizon import Anchor
from tome.pack_writer import BookText, ChapterText, PackWriter
from tome.userdb import UserDB


def test_library_and_horizon_anchor(tmp_path, tiny_pack):
    db = UserDB(tmp_path / "user.sqlite")
    pack_id = db.import_pack(tiny_pack)
    assert pack_id == "tiny" and [p["pack_id"] for p in db.packs()] == ["tiny"]

    # No horizon yet: nothing is visible.
    assert db.resolve_horizon("tiny").pos == 0
    with db.open_reader("tiny") as r:
        assert r.query("SELECT * FROM h_passages") == []

    db.set_horizon("tiny", Anchor(1, 2), set_via="chapter_picker")
    assert db.horizon_anchor("tiny") == Anchor(1, 2)
    with db.open_reader("tiny") as r:
        assert r.horizon == 4
    db.close()


def test_reimport_keeps_horizon_and_resolves_against_new_pack(tmp_path, tiny_pack):
    """A recompile can shift pos; the stored anchor is re-resolved on open."""
    db = UserDB(tmp_path / "user.sqlite")
    db.import_pack(tiny_pack)
    db.set_horizon("tiny", Anchor(2, 1))
    assert db.resolve_horizon("tiny").pos == 6

    # Recompile with an extra passage in book 1: everything after shifts by one.
    v2 = tmp_path / "tiny-v2.tome"
    w = PackWriter(v2, pack_id="tiny", series_title="Tiny")
    for b in (1, 2):
        chs = [
            ChapterText(f"c{c}", [f"Book {b} chapter {c} passage {p} text" for p in (1, 2)])
            for c in (1, 2)
        ]
        if b == 1:
            chs[0].passages.append("an extra passage added by the recompile")
        w.add_book(b, BookText(f"Book {b}", chs))
    w.finalize(pack_version=2)
    w.close()
    db.import_pack(v2)
    assert db.packs()[0]["pack_version"] == 2
    assert db.horizon_anchor("tiny") == Anchor(2, 1)
    assert db.resolve_horizon("tiny").pos == 7
    db.close()


def test_unknown_pack(tmp_path):
    db = UserDB(tmp_path / "user.sqlite")
    with pytest.raises(KeyError):
        db.open_reader("nope")
