"""Write side of a series pack. Used only by the compiler at ingestion time.

Reading never goes through this module: see ``tome.horizon``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tome import COMPILER_VERSION
from tome.db import connect_rw, latest_version
from tome.quote import locate_quote
from tome.text import clean, clean_paragraphs, fingerprint, fold, word_count


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class ChapterText:
    title: str
    passages: list[str]


@dataclass
class BookText:
    title: str
    chapters: list[ChapterText]
    source_file: str | None = None
    source_sha256: str | None = None


@dataclass
class QuoteStats:
    candidates: int = 0
    dropped: int = 0
    dropped_examples: list[dict] = field(default_factory=list)


class ReadingOrderViolation(ValueError):
    """A derived row used text beyond the compiler's current reading cursor."""


class PackWriter:
    """Builds a pack file. Positions are assigned in reading order as books are added."""

    def __init__(self, path: str | Path, *, pack_id: str, series_title: str, overwrite=False):
        self.path = Path(path)
        if self.path.exists():
            if not overwrite:
                raise FileExistsError(self.path)
            self.path.unlink()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection = connect_rw(self.path, "pack")
        self.pack_id = pack_id
        self.series_title = series_title
        self.next_pos = 1
        # Compiler reading cursor (invariant 3). When set, no derived row may
        # have max_source_pos beyond it.
        self.cursor: int | None = None
        self.quote_stats: dict[int, QuoteStats] = {}

    # ------------------------------------------------------------ runs ----
    def start_run(
        self,
        kind: str,
        *,
        llm_provider=None,
        llm_model=None,
        prompt_version=None,
        params: dict | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (kind, started_at, compiler_version, llm_provider, llm_model,"
            " prompt_version, params_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                utcnow(),
                COMPILER_VERSION,
                llm_provider,
                llm_model,
                prompt_version,
                json.dumps(params or {}, sort_keys=True),
            ),
        )
        self.quote_stats[cur.lastrowid] = QuoteStats()
        return cur.lastrowid

    def finish_run(
        self,
        run_id: int,
        *,
        stats: dict | None = None,
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=None,
    ) -> None:
        q = self.quote_stats.get(run_id, QuoteStats())
        merged = {"quote_candidates": q.candidates, "quote_dropped": q.dropped, **(stats or {})}
        self.conn.execute(
            "UPDATE runs SET finished_at=?, stats_json=?, prompt_tokens=?, completion_tokens=?,"
            " cost_usd=? WHERE run_id=?",
            (
                utcnow(),
                json.dumps(merged, sort_keys=True),
                prompt_tokens,
                completion_tokens,
                cost_usd,
                run_id,
            ),
        )

    # ---------------------------------------------------------- source ----
    def add_book(self, number: int, book: BookText) -> int:
        """Append a book after all previous ones. Returns book_id."""
        start = self.next_pos
        cur = self.conn.execute(
            "INSERT INTO books (number, title, start_pos, end_pos, source_file, source_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (number, book.title, start, start, book.source_file, book.source_sha256),
        )
        book_id = cur.lastrowid
        for ch_no, chapter in enumerate(book.chapters, start=1):
            self._add_chapter(book_id, ch_no, chapter)
        end = self.next_pos - 1
        if end < start:
            raise ValueError(f"book {number} has no passages")
        self.conn.execute("UPDATE books SET end_pos=? WHERE book_id=?", (end, book_id))
        return book_id

    def _add_chapter(self, book_id: int, number: int, chapter: ChapterText) -> int:
        texts = [clean_paragraphs(t) for t in chapter.passages if clean(t)]
        if not texts:
            raise ValueError(f"chapter {number} ({chapter.title!r}) has no text")
        start = self.next_pos
        end = start + len(texts) - 1
        cur = self.conn.execute(
            "INSERT INTO chapters (book_id, number, title, start_pos, end_pos)"
            " VALUES (?, ?, ?, ?, ?)",
            (book_id, number, clean(chapter.title), start, end),
        )
        chapter_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO passages (chapter_id, pos, seq, text, word_count, fingerprint)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (chapter_id, start + i, i, t, word_count(t), fingerprint(t))
                for i, t in enumerate(texts)
            ],
        )
        self.next_pos = end + 1
        return chapter_id

    def passage(self, passage_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM passages WHERE passage_id=?", (passage_id,)
        ).fetchone()
        if row is None:
            raise KeyError(passage_id)
        return row

    def passage_at(self, pos: int) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM passages WHERE pos=?", (pos,)).fetchone()
        if row is None:
            raise KeyError(pos)
        return row

    def chapter(self, book_number: int, chapter_number: int) -> sqlite3.Row:
        return self.conn.execute(
            "SELECT c.* FROM chapters c JOIN books b USING (book_id)"
            " WHERE b.number=? AND c.number=?",
            (book_number, chapter_number),
        ).fetchone()

    # --------------------------------------------------------- derived ----
    def _check_cursor(self, max_source_pos: int) -> None:
        if self.cursor is not None and max_source_pos > self.cursor:
            raise ReadingOrderViolation(
                f"max_source_pos {max_source_pos} is beyond the reading cursor {self.cursor}"
            )

    def _insert(self, table: str, row: dict) -> int:
        self._check_cursor(row["max_source_pos"])
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self.conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values())
        )
        return cur.lastrowid

    def add_entity(
        self,
        *,
        kind: str,
        first_pos: int,
        run_id: int,
        max_source_pos=None,
        attributes: dict | None = None,
    ) -> int:
        return self._insert(
            "entities",
            {
                "kind": kind,
                "first_pos": first_pos,
                "attributes_json": json.dumps(attributes or {}, sort_keys=True),
                "max_source_pos": max_source_pos or first_pos,
                "run_id": run_id,
            },
        )

    def add_alias(
        self,
        *,
        entity_id: int,
        surface_form: str,
        established_at: int,
        run_id: int,
        evidence_passage_id=None,
        max_source_pos=None,
    ) -> int:
        return self._insert(
            "aliases",
            {
                "entity_id": entity_id,
                "surface_form": surface_form,
                "normalized": " ".join(fold(surface_form).split()),
                "established_at": established_at,
                "evidence_passage_id": evidence_passage_id,
                "max_source_pos": max_source_pos or established_at,
                "run_id": run_id,
            },
        )

    def add_identity(
        self,
        *,
        entity_id: int,
        same_as_entity_id: int,
        established_at: int,
        run_id: int,
        evidence_passage_id=None,
        max_source_pos=None,
    ) -> int:
        return self._insert(
            "entity_identities",
            {
                "entity_id": entity_id,
                "same_as_entity_id": same_as_entity_id,
                "established_at": established_at,
                "evidence_passage_id": evidence_passage_id,
                "max_source_pos": max_source_pos or established_at,
                "run_id": run_id,
            },
        )

    def add_observation(
        self,
        *,
        sentence: str,
        subject_entity_id: int,
        predicate: str,
        evidence_passage_id: int,
        quote: str,
        run_id: int,
        status="stated",
        object_entity_id=None,
        object_text=None,
        claimed_by_entity_id=None,
        max_source_pos=None,
    ) -> int | None:
        """Insert an observation, or drop it (return None) if its quote doesn't verify."""
        stats = self.quote_stats.setdefault(run_id, QuoteStats())
        stats.candidates += 1
        passage = self.passage(evidence_passage_id)
        span = locate_quote(passage["text"], quote)
        if span is None:
            stats.dropped += 1
            if len(stats.dropped_examples) < 50:
                stats.dropped_examples.append(
                    {"pos": passage["pos"], "quote": quote, "sentence": sentence}
                )
            return None
        start, end = span
        return self._insert(
            "observations",
            {
                "sentence": sentence,
                "subject_entity_id": subject_entity_id,
                "predicate": predicate,
                "object_entity_id": object_entity_id,
                "object_text": object_text,
                "status": status,
                "claimed_by_entity_id": claimed_by_entity_id,
                "evidence_passage_id": evidence_passage_id,
                "quote_span": passage["text"][start:end],
                "quote_start": start,
                "quote_end": end,
                "pos": passage["pos"],
                "max_source_pos": max_source_pos or passage["pos"],
                "run_id": run_id,
            },
        )

    def add_relationship(
        self,
        *,
        source_entity_id: int,
        target_entity_id: int,
        rel_type: str,
        description: str,
        pos: int,
        run_id: int,
        evidence_passage_id=None,
        max_source_pos=None,
    ) -> int:
        return self._insert(
            "relationships",
            {
                "source_entity_id": source_entity_id,
                "target_entity_id": target_entity_id,
                "rel_type": rel_type,
                "description": description,
                "evidence_passage_id": evidence_passage_id,
                "pos": pos,
                "max_source_pos": max_source_pos or pos,
                "run_id": run_id,
            },
        )

    def add_profile(
        self,
        *,
        entity_id: int,
        checkpoint_pos: int,
        display_name: str,
        profile_text: str,
        max_source_pos: int,
        run_id: int,
        prev_profile_id=None,
    ) -> int:
        return self._insert(
            "entity_profiles",
            {
                "entity_id": entity_id,
                "checkpoint_pos": checkpoint_pos,
                "display_name": display_name,
                "profile_text": profile_text,
                "prev_profile_id": prev_profile_id,
                "max_source_pos": max_source_pos,
                "run_id": run_id,
            },
        )

    def add_chapter_summary(
        self, *, chapter_id: int, summary_text: str, run_id: int, max_source_pos: int | None = None
    ) -> int:
        if max_source_pos is None:
            max_source_pos = self.conn.execute(
                "SELECT end_pos FROM chapters WHERE chapter_id=?", (chapter_id,)
            ).fetchone()[0]
        return self._insert(
            "chapter_summaries",
            {
                "chapter_id": chapter_id,
                "summary_text": summary_text,
                "max_source_pos": max_source_pos,
                "run_id": run_id,
            },
        )

    def add_rollup(
        self,
        *,
        kind: str,
        text: str,
        max_source_pos: int,
        run_id: int,
        book_id=None,
        through_chapter_id=None,
    ) -> int:
        return self._insert(
            "rollups",
            {
                "kind": kind,
                "book_id": book_id,
                "through_chapter_id": through_chapter_id,
                "text": text,
                "max_source_pos": max_source_pos,
                "run_id": run_id,
            },
        )

    def add_anticipated_qa(
        self,
        *,
        chapter_id: int,
        question: str,
        answer: str,
        evidence_passage_ids: Sequence[int],
        max_source_pos: int,
        run_id: int,
    ) -> int:
        cited = [self.passage(pid)["pos"] for pid in evidence_passage_ids]
        if any(p > max_source_pos for p in cited):
            raise ValueError("anticipated answer cites a passage beyond its max_source_pos")
        return self._insert(
            "anticipated_qa",
            {
                "chapter_id": chapter_id,
                "question": question,
                "answer": answer,
                "evidence_passage_ids": json.dumps(list(evidence_passage_ids)),
                "max_source_pos": max_source_pos,
                "run_id": run_id,
            },
        )

    def add_embeddings(
        self, rows: Iterable[tuple[str, int, bytes, int]], *, model_id: str, dim: int, run_id: int
    ) -> None:
        """rows: (owner_table, owner_id, float32 vector bytes, max_source_pos)."""
        for owner_table, owner_id, vec, max_source_pos in rows:
            self._insert(
                "embeddings",
                {
                    "owner_table": owner_table,
                    "owner_id": owner_id,
                    "model_id": model_id,
                    "dim": dim,
                    "vector": vec,
                    "max_source_pos": max_source_pos,
                    "run_id": run_id,
                },
            )

    # -------------------------------------------------------- finalise ----
    def finalize(
        self,
        *,
        pack_version: int = 1,
        llm_model: str | None = None,
        embedding_model_id: str | None = None,
    ) -> str:
        """Build the FTS index, write the manifest and return the content hash."""
        self.conn.execute("INSERT INTO passages_fts(passages_fts) VALUES ('rebuild')")
        content_hash = compute_content_hash(self.conn)
        self.conn.execute("DELETE FROM manifest")
        self.conn.execute(
            "INSERT INTO manifest (singleton, pack_id, series_title, pack_version, schema_version,"
            " compiler_version, llm_model, embedding_model_id, content_hash, compiled_at)"
            " VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.pack_id,
                self.series_title,
                pack_version,
                latest_version("pack"),
                COMPILER_VERSION,
                llm_model,
                embedding_model_id,
                content_hash,
                utcnow(),
            ),
        )
        self.conn.execute("ANALYZE")
        return content_hash

    def close(self) -> None:
        self.conn.close()


# Tables excluded from the content hash: provenance and bookkeeping that differ
# between otherwise identical compiles.
_HASH_EXCLUDE = {"manifest", "runs", "sqlite_stat1", "sqlite_stat4"}


def compute_content_hash(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            " AND name NOT LIKE 'passages_fts%' ORDER BY name"
        )
    ]
    for table in tables:
        if table in _HASH_EXCLUDE:
            continue
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] != "run_id"]
        h.update(table.encode())
        for row in conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid"):
            h.update(json.dumps(list(row), default=lambda b: b.hex()).encode())
    return h.hexdigest()
