"""user.sqlite: the reader's library of packs and their horizon anchor per series."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tome.db import connect_rw, latest_version
from tome.horizon import Anchor, HorizonReader, PackVersionError, Resolution, resolve_anchor
from tome.pack_writer import utcnow


class UserDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = connect_rw(self.path, "user")

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------- library ----
    def import_pack(self, pack_path: str | Path) -> str:
        """Register a pack (or replace the previous version of the same series)."""
        pack_path = Path(pack_path).resolve()
        with sqlite3.connect(f"file:{pack_path}?mode=ro", uri=True) as pconn:
            pconn.row_factory = sqlite3.Row
            m = pconn.execute("SELECT * FROM manifest").fetchone()
        if m is None:
            raise ValueError(f"{pack_path} has no manifest; was it finalised?")
        if m["schema_version"] > latest_version("pack"):
            raise PackVersionError(f"pack schema v{m['schema_version']} is too new")
        self.conn.execute(
            "INSERT INTO library (pack_id, series_title, path, pack_version, schema_version,"
            " embedding_model_id, content_hash, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(pack_id) DO UPDATE SET series_title=excluded.series_title,"
            " path=excluded.path, pack_version=excluded.pack_version,"
            " schema_version=excluded.schema_version,"
            " embedding_model_id=excluded.embedding_model_id,"
            " content_hash=excluded.content_hash, imported_at=excluded.imported_at",
            (
                m["pack_id"],
                m["series_title"],
                str(pack_path),
                m["pack_version"],
                m["schema_version"],
                m["embedding_model_id"],
                m["content_hash"],
                utcnow(),
            ),
        )
        return m["pack_id"]

    def packs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM library ORDER BY series_title").fetchall()

    def pack_path(self, pack_id: str) -> Path:
        row = self.conn.execute("SELECT path FROM library WHERE pack_id=?", (pack_id,)).fetchone()
        if row is None:
            raise KeyError(f"no pack {pack_id!r} in the library")
        return Path(row["path"])

    # --------------------------------------------------------- horizons ----
    def set_horizon(self, pack_id: str, anchor: Anchor, *, set_via: str = "manual") -> None:
        self.conn.execute(
            "INSERT INTO horizons (pack_id, book_number, chapter_number, fingerprint, set_via,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(pack_id) DO UPDATE SET book_number=excluded.book_number,"
            " chapter_number=excluded.chapter_number, fingerprint=excluded.fingerprint,"
            " set_via=excluded.set_via, updated_at=excluded.updated_at",
            (pack_id, anchor.book, anchor.chapter, anchor.fingerprint, set_via, utcnow()),
        )

    def horizon_anchor(self, pack_id: str) -> Anchor | None:
        row = self.conn.execute("SELECT * FROM horizons WHERE pack_id=?", (pack_id,)).fetchone()
        if row is None:
            return None
        return Anchor(row["book_number"], row["chapter_number"], row["fingerprint"])

    def resolve_horizon(self, pack_id: str) -> Resolution:
        anchor = self.horizon_anchor(pack_id)
        if anchor is None:
            return Resolution(0, True, "no horizon set; nothing is visible")
        return resolve_anchor(self.pack_path(pack_id), anchor)

    def open_reader(self, pack_id: str) -> HorizonReader:
        """The normal way into a pack: at the reader's own stored horizon."""
        return HorizonReader(self.pack_path(pack_id), self.resolve_horizon(pack_id).pos)
