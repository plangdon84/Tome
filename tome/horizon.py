"""Horizon-safe data access: the only way to read a series pack at reading time.

How it works (all plain SQL, so it ports to SQLite-WASM in the PWA):

1. The pack is opened read-only.
2. For every non-public table, a TEMP VIEW ``h_<table>`` is created with the
   horizon baked in as a literal: every horizon column the table has
   (``max_source_pos``, ``established_at``, ``pos``, ``start_pos``) must be
   ``<= horizon``. A table with none of those columns gets no view at all.
3. An SQLite authorizer is installed. From then on, the connection can read
   public tables (manifest, books, runs) and the ``h_*`` views, and nothing
   else: direct reads of protected tables, new views, ATTACH, writes and
   pragmas are all refused by SQLite itself.

New tables are protected by default: anything not listed in
``PUBLIC_TABLES`` is either reachable through a filtered view or not at all.

Anchors (book, chapter, fingerprint) are converted to a ``pos`` here too,
rounding backwards whenever the match is uncertain (invariant 6).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tome.db import latest_version
from tome.text import fingerprint as make_fingerprint
from tome.text import words

PUBLIC_TABLES = frozenset({"manifest", "books", "runs"})
HORIZON_COLUMNS = ("max_source_pos", "established_at", "pos", "start_pos")
FTS_TABLE = "passages_fts"
FTS_VIEW = "h_passages_fts"
# Pragmas FTS5 issues internally. Nothing else is allowed.
_ALLOWED_PRAGMAS = frozenset({"data_version"})


class HorizonError(RuntimeError):
    pass


class PackVersionError(HorizonError):
    pass


# ------------------------------------------------------------------ anchors --


@dataclass(frozen=True)
class Anchor:
    """A horizon that survives recompiles.

    * ``fingerprint is None``: the reader has *finished* chapter ``chapter``
      of book ``book`` (``chapter == 0``: not started the book).
    * otherwise: the reader is *in* the passage of that chapter whose
      fingerprint this is, and has not finished it.
    """

    book: int
    chapter: int
    fingerprint: str | None = None

    _SPEC = re.compile(r"^\s*b(?:ook)?\s*(\d+)\s*(?:,|\s)\s*ch(?:apter)?\s*(\d+)\s*$", re.I)

    @classmethod
    def parse(cls, spec: str) -> Anchor:
        """Parse ``"b3 ch10"`` / ``"book 3 chapter 10"`` (= finished that chapter)."""
        m = cls._SPEC.match(spec)
        if not m:
            raise ValueError(f"expected something like 'b3 ch10', got {spec!r}")
        return cls(int(m.group(1)), int(m.group(2)))

    def __str__(self) -> str:
        s = f"b{self.book} ch{self.chapter}"
        return s + (f" @ '{self.fingerprint}'" if self.fingerprint else "")


@dataclass(frozen=True)
class Resolution:
    pos: int
    exact: bool
    reason: str


def _structure_conn(pack: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(pack).resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_anchor(pack: str | Path, anchor: Anchor) -> Resolution:
    """Convert an anchor to a horizon ``pos``. Never rounds forwards."""
    with _structure_conn(pack) as conn:
        return _resolve(conn, anchor)


def _resolve(conn: sqlite3.Connection, a: Anchor) -> Resolution:
    book = conn.execute("SELECT * FROM books WHERE number=?", (a.book,)).fetchone()
    if book is None:
        prev = conn.execute(
            "SELECT max(end_pos) FROM books WHERE number < ?", (a.book,)
        ).fetchone()[0]
        return Resolution(prev or 0, False, f"book {a.book} not in pack; end of an earlier book")
    if a.chapter == 0:
        return Resolution(book["start_pos"] - 1, True, "start of book")

    chapter = conn.execute(
        "SELECT * FROM chapters WHERE book_id=? AND number=?", (book["book_id"], a.chapter)
    ).fetchone()
    if chapter is None:
        prev = conn.execute(
            "SELECT max(end_pos) FROM chapters WHERE book_id=? AND number < ?",
            (book["book_id"], a.chapter),
        ).fetchone()[0]
        pos = prev if prev is not None else book["start_pos"] - 1
        return Resolution(
            pos, False, f"chapter {a.chapter} not in book {a.book}; end of an earlier chapter"
        )
    if a.fingerprint is None:
        return Resolution(chapter["end_pos"], True, "finished chapter")

    target = " ".join(words(a.fingerprint))
    rows = conn.execute(
        "SELECT pos, fingerprint FROM passages WHERE chapter_id=? ORDER BY pos",
        (chapter["chapter_id"],),
    ).fetchall()
    exact = [r["pos"] for r in rows if r["fingerprint"] == target]
    if len(exact) == 1:
        return Resolution(exact[0] - 1, True, "in passage (fingerprint matched)")
    if exact:
        return Resolution(min(exact) - 1, False, "fingerprint ambiguous; earliest match")
    # Edition drift: accept a long-enough prefix match in either direction.
    if len(target.split()) >= 6:
        prefix = [
            r["pos"]
            for r in rows
            if r["fingerprint"].startswith(target) or target.startswith(r["fingerprint"])
        ]
        if prefix:
            return Resolution(min(prefix) - 1, False, "fingerprint prefix match; earliest")
    return Resolution(
        chapter["start_pos"] - 1, False, "fingerprint not found; rounded back to chapter start"
    )


def anchor_for_pos(pack: str | Path, pos: int) -> Anchor:
    """The anchor to store for horizon ``pos`` (inverse of ``resolve_anchor``)."""
    with _structure_conn(pack) as conn:
        chapter = conn.execute(
            "SELECT c.number AS ch, b.number AS bk FROM chapters c JOIN books b USING (book_id)"
            " WHERE c.end_pos = ?",
            (pos,),
        ).fetchone()
        if chapter is not None:
            return Anchor(chapter["bk"], chapter["ch"])
        nxt = conn.execute(
            "SELECT p.fingerprint, c.number AS ch, b.number AS bk, c.start_pos"
            " FROM passages p JOIN chapters c USING (chapter_id) JOIN books b USING (book_id)"
            " WHERE p.pos = ?",
            (pos + 1,),
        ).fetchone()
        if nxt is None:
            raise HorizonError(f"pos {pos} is outside the pack")
        if nxt["start_pos"] == pos + 1:  # start of a book, nothing read in it yet
            return Anchor(nxt["bk"], 0)
        return Anchor(nxt["bk"], nxt["ch"], nxt["fingerprint"])


def fingerprint_for_text(text: str) -> str:
    return make_fingerprint(text)


# ------------------------------------------------------------------ reader --


class HorizonReader:
    """Read-only, horizon-filtered view of a pack.

    All SQL issued through this object (including ``query``) can see only
    rows at or before ``horizon``.
    """

    def __init__(self, pack: str | Path, horizon: int):
        if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 0:
            raise HorizonError(f"horizon must be a non-negative int, got {horizon!r}")
        self.pack_path = Path(pack)
        if not self.pack_path.exists():
            raise FileNotFoundError(self.pack_path)
        self._horizon = horizon
        self._conn = sqlite3.connect(
            f"file:{self.pack_path.resolve()}?mode=ro", uri=True, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._check_version()
        self._views = self._create_views()
        self._conn.set_authorizer(self._authorize)

    @classmethod
    def at_anchor(cls, pack: str | Path, anchor: Anchor) -> HorizonReader:
        return cls(pack, resolve_anchor(pack, anchor).pos)

    @property
    def horizon(self) -> int:
        return self._horizon

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> HorizonReader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- setup --
    def _check_version(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > latest_version("pack"):
            raise PackVersionError(
                f"pack schema v{version} is newer than this app (v{latest_version('pack')})"
            )

    def _create_views(self) -> frozenset[str]:
        h = self._horizon
        tables = [
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE ?",
                (f"{FTS_TABLE}%",),
            )
        ]
        views = set()
        for table in tables:
            if table in PUBLIC_TABLES:
                continue
            cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            conds = [f"{c} <= {h}" for c in HORIZON_COLUMNS if c in cols]
            if not conds:
                continue  # protected and unreachable
            self._conn.execute(
                f"CREATE TEMP VIEW h_{table} AS SELECT * FROM main.{table}"
                f" WHERE {' AND '.join(conds)}"
            )
            views.add(f"h_{table}")
        self._conn.execute(
            f"CREATE TEMP VIEW {FTS_VIEW} AS SELECT rowid AS passage_id, {FTS_TABLE} AS fts,"
            f" rank AS rank FROM main.{FTS_TABLE}"
            f" WHERE rowid IN (SELECT passage_id FROM main.passages WHERE pos <= {h})"
        )
        views.add(FTS_VIEW)
        return frozenset(views)

    def _authorize(self, action, arg1, arg2, db_name, source):
        if action == sqlite3.SQLITE_READ:
            table = arg1
            if db_name == "temp" and table in self._views:
                return sqlite3.SQLITE_OK
            if table in PUBLIC_TABLES or table in ("sqlite_master", "sqlite_temp_master"):
                return sqlite3.SQLITE_OK
            if source in self._views:
                return sqlite3.SQLITE_OK
            if table == FTS_TABLE and arg2 == "ROWID":
                return sqlite3.SQLITE_OK  # a bare integer id; content columns stay denied
            if table.startswith(f"{FTS_TABLE}_"):
                return sqlite3.SQLITE_OK  # FTS5 shadow tables, read by FTS5 internals
            return sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and arg1 in _ALLOWED_PRAGMAS and arg2 is None:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    # -- generic access --
    def query(self, sql: str, params: Sequence | dict = ()) -> list[sqlite3.Row]:
        """Run read-only SQL against the ``h_*`` views (and public tables)."""
        try:
            return self._conn.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as exc:
            if "not authorized" in str(exc) or "prohibited" in str(exc):
                raise HorizonError(f"blocked by the horizon layer: {exc}") from exc
            raise

    def one(self, sql: str, params: Sequence | dict = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # -- public metadata --
    def manifest(self) -> dict:
        row = self.one("SELECT * FROM manifest")
        return dict(row) if row else {}

    def books(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM books ORDER BY number")

    # -- structure --
    def chapters(self) -> list[sqlite3.Row]:
        return self.query(
            "SELECT c.*, b.number AS book_number FROM h_chapters c JOIN books b USING (book_id)"
            " ORDER BY c.start_pos"
        )

    def passage(self, passage_id: int) -> sqlite3.Row | None:
        return self.one("SELECT * FROM h_passages WHERE passage_id = ?", (passage_id,))

    def search_passages(self, text: str, limit: int = 10) -> list[sqlite3.Row]:
        """Keyword search over passages at or before the horizon (FTS5, bm25)."""
        q = fts_query(text)
        if not q:
            return []
        # MATERIALIZED keeps the FTS view from being flattened into the join,
        # so every column read stays attributed to a horizon view.
        return self.query(
            "WITH hits AS MATERIALIZED ("
            "  SELECT passage_id, rank FROM h_passages_fts WHERE fts MATCH ?)"
            " SELECT p.*, hits.rank FROM hits JOIN h_passages p USING (passage_id)"
            " ORDER BY hits.rank LIMIT ?",
            (q, limit),
        )

    # -- entities --
    def entities_for_name(self, name: str) -> list[sqlite3.Row]:
        """Entities a surface form refers to, as far as the reader knows."""
        norm = " ".join(words(name))
        return self.query(
            "SELECT DISTINCT e.* FROM h_aliases a JOIN h_entities e USING (entity_id)"
            " WHERE a.normalized = ?",
            (norm,),
        )

    def aliases(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM h_aliases ORDER BY length(normalized) DESC")

    def names(self, entity_id: int) -> list[str]:
        return [
            r["surface_form"]
            for r in self.query(
                "SELECT surface_form FROM h_aliases WHERE entity_id = ? ORDER BY established_at",
                (entity_id,),
            )
        ]

    def identities(self, entity_id: int) -> list[int]:
        """Other entities revealed (by the horizon) to be the same as ``entity_id``."""
        rows = self.query(
            "SELECT same_as_entity_id AS other FROM h_entity_identities WHERE entity_id = ?"
            " UNION SELECT entity_id FROM h_entity_identities WHERE same_as_entity_id = ?",
            (entity_id, entity_id),
        )
        return [r["other"] for r in rows]

    def latest_profile(self, entity_id: int) -> sqlite3.Row | None:
        return self.one(
            "SELECT * FROM h_entity_profiles WHERE entity_id = ?"
            " ORDER BY max_source_pos DESC, profile_id DESC LIMIT 1",
            (entity_id,),
        )

    def observations(self, entity_id: int, since_pos: int = 0) -> list[sqlite3.Row]:
        return self.query(
            "SELECT o.*, p.pos AS evidence_pos FROM h_observations o"
            " JOIN h_passages p ON p.passage_id = o.evidence_passage_id"
            " WHERE (o.subject_entity_id = ? OR o.object_entity_id = ?) AND o.pos > ?"
            " ORDER BY o.pos",
            (entity_id, entity_id, since_pos),
        )

    def relationships(self, entity_id: int) -> list[sqlite3.Row]:
        return self.query(
            "SELECT * FROM h_relationships WHERE source_entity_id = ? OR target_entity_id = ?"
            " ORDER BY pos",
            (entity_id, entity_id),
        )

    # -- summaries and anticipated Q&A --
    def chapter_summaries(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = (
            "SELECT s.*, c.number AS chapter_number, c.title AS chapter_title"
            " FROM h_chapter_summaries s JOIN h_chapters c USING (chapter_id)"
            " ORDER BY s.max_source_pos DESC"
        )
        rows = self.query(sql + (" LIMIT ?" if limit else ""), (limit,) if limit else ())
        return list(reversed(rows))

    def latest_rollup(self, kind: str = "story_so_far") -> sqlite3.Row | None:
        return self.one(
            "SELECT * FROM h_rollups WHERE kind = ? ORDER BY max_source_pos DESC LIMIT 1", (kind,)
        )

    def anticipated_qa(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM h_anticipated_qa ORDER BY max_source_pos")


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 query (OR of quoted terms)."""
    terms = [w for w in words(text) if len(w) > 1]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))
