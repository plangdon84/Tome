"""Download public-domain EPUBs into the gitignored ``corpus/`` directory.

Only public-domain works are listed here. Copyrighted books are never
downloaded or processed in this environment; they live in ``library/`` on the
reader's own machine.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_DIR = Path("corpus")
USER_AGENT = "tome/0.0 (personal reading-companion research; public-domain texts only)"


@dataclass(frozen=True)
class CorpusBook:
    key: str
    title: str
    sources: tuple[str, ...]  # tried in order


SE = "https://standardebooks.org/ebooks"
PG = "https://www.gutenberg.org/ebooks"

CATALOG: dict[str, CorpusBook] = {
    b.key: b
    for b in [
        CorpusBook(
            "monte-cristo",
            "The Count of Monte Cristo (Dumas, Chapman & Hall translation)",
            (
                f"{SE}/alexandre-dumas/the-count-of-monte-cristo/chapman-and-hall/downloads/"
                "alexandre-dumas_the-count-of-monte-cristo_chapman-and-hall.epub?source=download",
                f"{PG}/1184.epub.noimages",
            ),
        ),
        # Same novel from Project Gutenberg: its TOC nests chapters under five
        # volumes, which makes it a real-world fixture for omnibus splitting.
        CorpusBook(
            "monte-cristo-gutenberg",
            "The Count of Monte Cristo (Project Gutenberg #1184, nested volume TOC)",
            (f"{PG}/1184.epub.noimages",),
        ),
    ]
}


def _se(author: str, slug: str) -> str:
    return f"{SE}/{author}/{slug}/downloads/{author}_{slug}.epub?source=download"


# Oz: the multi-book public-domain series. Book 2 has a clean identity reveal
# (Tip is Ozma), and characters carry over between books.
OZ = [
    ("oz-1", "the-wonderful-wizard-of-oz", "The Wonderful Wizard of Oz"),
    ("oz-2", "the-marvelous-land-of-oz", "The Marvelous Land of Oz"),
    ("oz-3", "ozma-of-oz", "Ozma of Oz"),
    ("oz-4", "dorothy-and-the-wizard-in-oz", "Dorothy and the Wizard in Oz"),
    ("oz-5", "the-road-to-oz", "The Road to Oz"),
]
CATALOG.update(
    {
        key: CorpusBook(key, f"{title} (Baum)", (_se("l-frank-baum", slug),))
        for key, slug, title in OZ
    }
)
# Series keys expand to their books, in reading order.
SERIES: dict[str, list[str]] = {"oz": [key for key, _, _ in OZ]}


def expand(keys: list[str]) -> list[str]:
    return [k for key in keys for k in SERIES.get(key, [key])]


def fetch(
    key: str,
    dest_dir: Path = DEFAULT_DIR,
    *,
    force: bool = False,
    client: httpx.Client | None = None,
) -> Path:
    """Download ``key`` to ``dest_dir/<key>.epub`` and return the path."""
    book = CATALOG[key]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{key}.epub"
    if dest.exists() and not force:
        return dest
    own_client = client is None
    client = client or httpx.Client(
        follow_redirects=True, timeout=120, headers={"User-Agent": USER_AGENT}
    )
    errors = []
    try:
        for url in book.sources:
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                errors.append(f"{url}: {exc}")
                continue
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(resp.content)
            if not _looks_like_epub(tmp):
                tmp.unlink()
                errors.append(f"{url}: not an EPUB")
                continue
            tmp.replace(dest)
            dest.with_suffix(".source").write_text(
                f"{url}\nsha256 {hashlib.sha256(dest.read_bytes()).hexdigest()}\n"
            )
            return dest
    finally:
        if own_client:
            client.close()
    raise RuntimeError(f"could not download {key}: " + "; ".join(errors))


def _looks_like_epub(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.read("mimetype").strip() == b"application/epub+zip"
    except (zipfile.BadZipFile, KeyError):
        return False
