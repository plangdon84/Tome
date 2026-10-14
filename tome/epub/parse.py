"""EPUB -> books -> chapters -> passages, with an omnibus-splitting hook.

Chapter detection uses the table of contents: every TOC entry that survives
front/back-matter filtering and has no surviving children is a chapter. A
chapter runs from its anchor to the next TOC target of any kind (another
chapter, a volume heading, an excluded entry such as a licence), so headings
and matter between chapters are not swallowed.

Book splitting is controlled by a layout file (TOML), because an omnibus
EPUB (e.g. seven books in one file) cannot be detected reliably:

    # library/harry-potter.layout.toml
    split = "toc"        # "none" (default) | "toc" | "manual"
    book_level = 1       # split = "toc": TOC depth whose entries are books
    titles = ["Book One", "Book Two"]   # optional renames, in order
    exclude = ["^Map of"]               # extra TOC titles (regex) to drop, with their children

    # split = "manual": each book starts at the first TOC entry matching `start`
    [[books]]
    title = "Book One"
    start = "^Chapter One$"

The layout file can sit next to the EPUB as ``<name>.layout.toml``.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from tome.epub.passages import split_passages
from tome.epub.reader import Epub, TocEntry, open_epub
from tome.pack_writer import BookText, ChapterText
from tome.text import fold, word_count

MATTER_TYPES = {
    "frontmatter",
    "backmatter",
    "titlepage",
    "halftitlepage",
    "imprint",
    "colophon",
    "copyright-page",
    "toc",
    "landmarks",
    "loi",
    "lot",
    "endnotes",
    "footnotes",
    "rearnotes",
    "index",
    "acknowledgments",
    "seriespage",
    "other-credits",
    "contributors",
    "errata",
    "cover",
    "dedication",
    "epigraph",
    "foreword",
    "preface",
    "introduction",
}
DEFAULT_EXCLUDE = [
    r"^(table of )?contents$",
    r"^title ?page$",
    r"^half ?title",
    r"^imprint$",
    r"^colophon$",
    r"^uncopyright$",
    r"^copyright",
    r"^(end|foot)?notes:?$",
    r"^about the (author|publisher)",
    r"^also by",
    r"^acknowledg",
    r"^dedication$",
    r"^cover$",
    r"project gutenberg",
    r"^(the )?full license",
    r"^index$",
    r"^bibliography$",
]


@dataclass
class Layout:
    split: str = "none"
    book_level: int = 1
    titles: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    books: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> Layout:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        layout = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if layout.split not in {"none", "toc", "manual"}:
            raise ValueError(f"layout split must be none|toc|manual, got {layout.split!r}")
        if layout.split == "manual" and not layout.books:
            raise ValueError("layout split = 'manual' needs [[books]] entries with title/start")
        return layout

    @classmethod
    def for_epub(cls, epub_path: str | Path, explicit: str | Path | None = None) -> Layout:
        if explicit:
            return cls.load(explicit)
        sidecar = Path(epub_path).with_suffix(".layout.toml")
        return cls.load(sidecar) if sidecar.exists() else cls()


@dataclass
class ParsedBook:
    title: str
    chapters: list[ChapterText]

    @property
    def passages(self) -> int:
        return sum(len(c.passages) for c in self.chapters)


@dataclass
class ParseResult:
    title: str
    books: list[ParsedBook]
    warnings: list[str]
    source_sha256: str
    hint: str | None = None

    def book_texts(self, source_file: str | None = None) -> list[BookText]:
        return [BookText(b.title, b.chapters, source_file, self.source_sha256) for b in self.books]


@dataclass
class _Node:
    entry: TocEntry
    level: int
    keep: bool
    children: list[_Node]
    start: tuple[int, int] | None  # (spine index, block index)

    def kept_leaves(self):
        kids = [c for c in self.children if c.has_kept()]
        if self.keep and not kids:
            yield self
        for c in kids:
            yield from c.kept_leaves()

    def has_kept(self) -> bool:
        return self.keep or any(c.has_kept() for c in self.children)


def parse_epub(path: str | Path, layout: Layout | None = None) -> ParseResult:
    path = Path(path)
    layout = layout or Layout.for_epub(path)
    epub = open_epub(path)
    try:
        return _parse(epub, layout, hashlib.sha256(path.read_bytes()).hexdigest())
    finally:
        epub.close()


def _is_matter(epub: Epub, spine_idx: int) -> bool:
    item = epub.spine[spine_idx]
    if not item.linear or "html" not in item.media_type:
        return True
    return bool(epub.document(item.href).epub_types & MATTER_TYPES)


def _parse(epub: Epub, layout: Layout, sha: str) -> ParseResult:
    warnings: list[str] = []
    exclude = [re.compile(p, re.I) for p in DEFAULT_EXCLUDE + layout.exclude]
    book_title_folded = fold(epub.title)

    def locate(entry: TocEntry) -> tuple[int, int] | None:
        si = epub.spine_index(entry.href)
        if si is None:
            return None
        if entry.fragment is None:
            return si, 0
        anchors = epub.document(entry.href).anchors
        if entry.fragment not in anchors:
            warnings.append(f"TOC anchor #{entry.fragment} not found in {entry.href}")
            return si, 0
        return si, anchors[entry.fragment]

    def build(entry: TocEntry, level: int, dropped: bool = False) -> _Node:
        # An exclude pattern drops the entry and everything under it (e.g. a
        # "Bonus Material" group); excluded children still mark boundaries.
        dropped = dropped or any(rx.search(entry.title) for rx in exclude)
        start = locate(entry)
        title_excluded = dropped or fold(entry.title) == book_title_folded
        keep = start is not None and not title_excluded and not _is_matter(epub, start[0])
        children = [build(c, level + 1, dropped) for c in entry.children]
        return _Node(entry, level, keep, children, start)

    roots = [build(e, 1) for e in epub.toc]
    all_nodes = [n for r in roots for n in _walk(r)]
    boundaries = sorted({n.start for n in all_nodes if n.start is not None})

    groups = _group_books(roots, layout, epub.title, warnings)
    hint = _omnibus_hint(roots, layout)

    if not any(chapters for _, chapters in groups):
        warnings.append("TOC gave no chapters; falling back to one chapter per spine document")
        groups = [(epub.title, None)]

    books = []
    for title, chapter_nodes in groups:
        if chapter_nodes is None:
            chapters = _spine_chapters(epub)
        else:
            chapter_nodes = sorted(chapter_nodes, key=lambda n: n.start)
            chapters = []
            for node in chapter_nodes:
                paragraphs = _extract(epub, node.start, boundaries)
                if word_count(" ".join(paragraphs)) == 0:
                    warnings.append(f"chapter {node.entry.title!r} has no text; skipped")
                    continue
                chapters.append(ChapterText(node.entry.title, split_passages(paragraphs)))
        if chapters:
            books.append(ParsedBook(title, chapters))
    return ParseResult(epub.title, books, warnings, sha, hint)


def _walk(node: _Node):
    yield node
    for c in node.children:
        yield from _walk(c)


def _group_books(roots: list[_Node], layout: Layout, title: str, warnings: list[str]):
    if layout.split == "none":
        return [(title, [leaf for r in roots for leaf in r.kept_leaves()])]

    if layout.split == "toc":
        level_nodes = [
            n
            for r in roots
            for n in _walk(r)
            if n.level == layout.book_level
            and n.has_kept()
            and any(c.has_kept() for c in n.children)
        ]
        if not level_nodes:
            warnings.append(
                f"split='toc': no TOC entries with chapters at level "
                f"{layout.book_level}; treating the EPUB as one book"
            )
            return [(title, [leaf for r in roots for leaf in r.kept_leaves()])]
        groups = []
        for i, node in enumerate(level_nodes):
            name = layout.titles[i] if i < len(layout.titles) else node.entry.title
            groups.append((name, [leaf for c in node.children for leaf in c.kept_leaves()]))
        return groups

    # manual
    leaves_in_order = [n for r in roots for n in _walk(r)]
    leaves = [leaf for r in roots for leaf in r.kept_leaves()]
    leaf_ids = {id(n) for n in leaves}
    groups: list[tuple[str, list[_Node]]] = []
    starts = [(b["title"], re.compile(b["start"], re.I)) for b in layout.books]
    current = None
    for node in leaves_in_order:
        for book_title, rx in starts:
            if rx.search(node.entry.title) and book_title not in [g[0] for g in groups]:
                current = (book_title, [])
                groups.append(current)
                break
        if id(node) in leaf_ids:
            if current is None:
                warnings.append(
                    f"chapter {node.entry.title!r} precedes the first manual book start; skipped"
                )
                continue
            current[1].append(node)
    missing = [t for t, _ in starts if t not in [g[0] for g in groups]]
    if missing:
        warnings.append(f"manual layout: no TOC entry matched the start of {missing}")
    return groups


def _omnibus_hint(roots: list[_Node], layout: Layout) -> str | None:
    if layout.split != "none":
        return None
    containers = [r for r in roots if r.has_kept() and any(c.has_kept() for c in r.children)]
    if len(containers) >= 2:
        names = ", ".join(repr(c.entry.title) for c in containers[:4])
        return (
            f"The TOC has {len(containers)} top-level groups ({names}...). If these are "
            'separate books (an omnibus), add a layout file with split = "toc".'
        )
    return None


def _extract(epub: Epub, start: tuple[int, int], boundaries: list[tuple[int, int]]) -> list[str]:
    """Non-heading paragraphs from ``start`` up to the next boundary or matter document."""
    following = [b for b in boundaries if b > start]
    end = following[0] if following else (len(epub.spine), 0)
    paragraphs: list[str] = []
    si, bi = start
    while (si, bi) < end and si < len(epub.spine):
        if si != start[0] and _is_matter(epub, si):
            break
        blocks = epub.document(epub.spine[si].href).blocks
        stop = end[1] if si == end[0] else len(blocks)
        paragraphs.extend(b.text for b in blocks[bi:stop] if not b.heading)
        si, bi = si + 1, 0
    return paragraphs


def _spine_chapters(epub: Epub) -> list[ChapterText]:
    chapters = []
    for i, item in enumerate(epub.spine):
        if _is_matter(epub, i):
            continue
        doc = epub.document(item.href)
        paragraphs = [b.text for b in doc.blocks if not b.heading]
        if word_count(" ".join(paragraphs)) == 0:
            continue
        chapters.append(
            ChapterText(doc.title or f"Section {len(chapters) + 1}", split_passages(paragraphs))
        )
    return chapters
