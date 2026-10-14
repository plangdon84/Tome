"""A small EPUB 2/3 reader: container -> OPF -> spine + TOC -> text blocks.

Only what Tome needs: spine order, the table of contents (EPUB3 nav or EPUB2
NCX) as a tree, and each content document as a list of text blocks with the
element ids that anchor into them (so a TOC entry ``file.xhtml#id`` can be
mapped to a block index).
"""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urldefrag

from lxml import etree, html

from tome.text import clean

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"

BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "dt",
    "dd",
    "pre",
    "blockquote",
    "div",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "hgroup",
    "figure",
    "figcaption",
    "table",
    "tr",
    "td",
    "th",
    "ul",
    "ol",
    "dl",
    "body",
    "main",
    "nav",
    "address",
    "caption",
    "tbody",
    "thead",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "head", "title", "svg", "math", "img"}
# epub:type values whose element (and contents) carry no story text.
SKIP_EPUB_TYPES = {"pagebreak", "noteref", "footnote", "endnote", "rearnote", "annoref"}


@dataclass
class TocEntry:
    title: str
    href: str  # path inside the zip, resolved
    fragment: str | None
    children: list[TocEntry] = field(default_factory=list)

    def walk(self, level: int = 1):
        yield self, level
        for child in self.children:
            yield from child.walk(level + 1)


@dataclass
class SpineItem:
    idref: str
    href: str
    media_type: str
    linear: bool


@dataclass
class Block:
    text: str
    heading: bool


@dataclass
class Document:
    href: str
    blocks: list[Block]
    anchors: dict[str, int]  # element id -> index of the first block at/after it
    epub_types: set[str]  # epub:type tokens on <body> and top-level sections
    title: str | None  # first heading text


@dataclass
class Epub:
    path: Path
    title: str
    creators: list[str]
    language: str | None
    spine: list[SpineItem]
    toc: list[TocEntry]
    _zip: zipfile.ZipFile
    _docs: dict[str, Document] = field(default_factory=dict)

    def document(self, href: str) -> Document:
        if href not in self._docs:
            self._docs[href] = _parse_document(href, self._zip.read(href))
        return self._docs[href]

    def spine_index(self, href: str) -> int | None:
        for i, item in enumerate(self.spine):
            if item.href == href:
                return i
        return None

    def close(self) -> None:
        self._zip.close()


def open_epub(path: str | Path) -> Epub:
    path = Path(path)
    zf = zipfile.ZipFile(path)
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", NS).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = etree.fromstring(zf.read(opf_path))

    def resolve(base_dir: str, href: str) -> tuple[str, str | None]:
        target, frag = urldefrag(unquote(href))
        return posixpath.normpath(posixpath.join(base_dir, target)), (frag or None)

    meta = opf.find("opf:metadata", NS)
    title = clean(" ".join(meta.find("dc:title", NS).itertext())) if meta is not None else path.stem
    creators = [clean("".join(e.itertext())) for e in meta.findall("dc:creator", NS)]
    lang_el = meta.find("dc:language", NS)

    manifest = {}
    nav_href = None
    for item in opf.find("opf:manifest", NS):
        if not isinstance(item.tag, str):
            continue
        href, _ = resolve(opf_dir, item.get("href"))
        manifest[item.get("id")] = (href, item.get("media-type", ""))
        if "nav" in (item.get("properties") or "").split():
            nav_href = href

    spine_el = opf.find("opf:spine", NS)
    spine = []
    for ref in spine_el:
        if not isinstance(ref.tag, str) or ref.get("idref") not in manifest:
            continue
        href, media_type = manifest[ref.get("idref")]
        spine.append(SpineItem(ref.get("idref"), href, media_type, ref.get("linear") != "no"))

    toc: list[TocEntry] = []
    if nav_href and nav_href in zf.namelist():
        toc = _parse_nav(zf.read(nav_href), posixpath.dirname(nav_href), resolve)
    if not toc:
        ncx_id = spine_el.get("toc")
        ncx_href = manifest.get(ncx_id, (None,))[0] if ncx_id else None
        if ncx_href is None:
            ncx_href = next(
                (h for h, mt in manifest.values() if mt == "application/x-dtbncx+xml"), None
            )
        if ncx_href and ncx_href in zf.namelist():
            toc = _parse_ncx(zf.read(ncx_href), posixpath.dirname(ncx_href), resolve)

    return Epub(
        path=path,
        title=title,
        creators=creators,
        language=lang_el.text if lang_el is not None else None,
        spine=spine,
        toc=toc,
        _zip=zf,
    )


def _parse_nav(data: bytes, base: str, resolve) -> list[TocEntry]:
    root = etree.fromstring(data)
    navs = root.iter(f"{{{NS['xhtml']}}}nav")
    toc_nav = None
    for nav in navs:
        if "toc" in (nav.get(EPUB_TYPE) or "").split():
            toc_nav = nav
            break
    if toc_nav is None:
        return []
    ol = toc_nav.find("xhtml:ol", NS)
    return _nav_list(ol, base, resolve) if ol is not None else []


def _nav_list(ol, base, resolve) -> list[TocEntry]:
    entries = []
    for li in ol.findall("xhtml:li", NS):
        a = li.find("xhtml:a", NS)
        sub = li.find("xhtml:ol", NS)
        children = _nav_list(sub, base, resolve) if sub is not None else []
        if a is None or not a.get("href"):
            if children:  # an unlinked grouping label: hoist its children
                label = li.find("xhtml:span", NS)
                title = clean("".join(label.itertext())) if label is not None else ""
                href, frag = children[0].href, children[0].fragment
                entries.append(TocEntry(title, href, frag, children))
            continue
        href, frag = resolve(base, a.get("href"))
        entries.append(TocEntry(clean("".join(a.itertext())), href, frag, children))
    return entries


def _parse_ncx(data: bytes, base: str, resolve) -> list[TocEntry]:
    root = etree.fromstring(data)
    nav_map = root.find("ncx:navMap", NS)
    return _ncx_points(nav_map, base, resolve) if nav_map is not None else []


def _ncx_points(parent, base, resolve) -> list[TocEntry]:
    entries = []
    for point in parent.findall("ncx:navPoint", NS):
        label = point.find("ncx:navLabel/ncx:text", NS)
        content = point.find("ncx:content", NS)
        if content is None:
            continue
        href, frag = resolve(base, content.get("src"))
        title = clean("".join(label.itertext())) if label is not None else ""
        entries.append(TocEntry(title, href, frag, _ncx_points(point, base, resolve)))
    return entries


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _epub_types(el) -> set[str]:
    return set((el.get(EPUB_TYPE) or el.get("epub:type") or "").split())


def _parse_document(href: str, data: bytes) -> Document:
    try:
        root = etree.fromstring(
            data, etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError:
        root = None
    if root is None:
        root = html.fromstring(data)
    body = next((el for el in root.iter() if _local(el.tag) == "body"), root)

    epub_types = _epub_types(body)
    for child in body:
        if _local(child.tag) in {"section", "article", "div"}:
            epub_types |= _epub_types(child)

    blocks: list[Block] = []
    anchors: dict[str, int] = {}

    def has_block_child(el) -> bool:
        return any(_local(c.tag) in BLOCK_TAGS for c in el)

    def inline_text(el) -> str:
        parts = []

        def rec(e):
            tag = _local(e.tag)
            if e.get("id"):
                anchors.setdefault(e.get("id"), len(blocks))
            if tag in SKIP_TAGS or _epub_types(e) & SKIP_EPUB_TYPES:
                if e.tail:
                    parts.append(e.tail)
                return
            if tag == "br":
                parts.append(" ")
            if e.text:
                parts.append(e.text)
            for c in e:
                rec(c)
            if e.tail and e is not el:
                parts.append(e.tail)

        rec(el)
        return clean("".join(parts))

    def walk(el, in_heading: bool):
        tag = _local(el.tag)
        if not tag or tag in SKIP_TAGS or _epub_types(el) & SKIP_EPUB_TYPES:
            return
        if el.get("id"):
            anchors.setdefault(el.get("id"), len(blocks))
        heading = (
            in_heading
            or tag in HEADING_TAGS
            or tag == "hgroup"
            or (tag == "header" and not el.xpath(".//*[local-name()='p'][string-length(.) > 200]"))
        )
        if tag in BLOCK_TAGS and not has_block_child(el):
            text = inline_text(el)
            if text:
                blocks.append(Block(text, heading))
            return
        if el.text and el.text.strip() and tag in BLOCK_TAGS:
            blocks.append(Block(clean(el.text), heading))
        for child in el:
            walk(child, heading)
            if child.tail and child.tail.strip() and tag in BLOCK_TAGS:
                blocks.append(Block(clean(child.tail), heading))

    walk(body, False)
    title = next((b.text for b in blocks if b.heading), None)
    return Document(href=href, blocks=blocks, anchors=anchors, epub_types=epub_types, title=title)
