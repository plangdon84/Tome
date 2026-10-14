"""Plain-SQL migrations for the two database files (series pack and user.sqlite).

Migrations live in ``tome/migrations/<kind>/NNNN_name.sql``. The applied
version is stored in ``PRAGMA user_version``. Each file runs once, in order,
inside a transaction.
"""

from __future__ import annotations

import re
import sqlite3
from importlib import resources
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migrations(kind: str) -> list[tuple[int, str, str]]:
    """Return ``(version, filename, sql)`` for every migration of ``kind``."""
    root = resources.files("tome") / "migrations" / kind
    found = []
    for entry in root.iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    versions = [v for v, _, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"{kind} migrations must be numbered 0001.. without gaps: {versions}")
    return found


def latest_version(kind: str) -> int:
    return len(migrations(kind))


def migrate(conn: sqlite3.Connection, kind: str) -> int:
    """Apply pending migrations of ``kind`` to ``conn``. Returns the new version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, name, sql in migrations(kind):
        if version <= current:
            continue
        try:
            conn.execute("BEGIN")
            # executescript would COMMIT first; run statements one by one instead.
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise RuntimeError(f"migration {kind}/{name} failed: {exc}") from exc
        current = version
    return current


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into complete statements (trigger bodies included)."""
    statements, buf = [], []
    for line in sql.splitlines(keepends=True):
        if not buf and (not line.strip() or line.lstrip().startswith("--")):
            continue
        buf.append(line)
        candidate = "".join(buf).strip()
        if sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buf = []
    if "".join(buf).strip():
        raise RuntimeError("migration ends with an incomplete statement")
    return statements


def connect_rw(path: str | Path, kind: str) -> sqlite3.Connection:
    """Open (creating if needed) a database for writing and bring it up to date."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn, kind)
    return conn
