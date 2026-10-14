"""Build small synthetic EPUBs for parser tests (no copyrighted text anywhere)."""

import zipfile
from pathlib import Path

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles></container>"""


def para(tag: str, n: int) -> str:
    return " ".join(f"{tag}w{i}" for i in range(n)) + "."


def xhtml(body: str, body_type: str = "bodymatter") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>x</title></head><body epub:type="{body_type}">{body}</body></html>"""


def nav_ol(entries) -> str:
    items = []
    for title, href, children in entries:
        sub = nav_ol(children) if children else ""
        items.append(f'<li><a href="{href}">{title}</a>{sub}</li>')
    return "<ol>" + "".join(items) + "</ol>"


def ncx_points(entries, counter=None) -> str:
    counter = counter if counter is not None else [0]
    out = []
    for title, href, children in entries:
        counter[0] += 1
        out.append(
            f'<navPoint id="n{counter[0]}" playOrder="{counter[0]}"><navLabel><text>{title}'
            f'</text></navLabel><content src="{href}"/>{ncx_points(children, counter)}</navPoint>'
        )
    return "".join(out)


def build_epub(
    path: Path,
    docs: dict[str, str],
    toc,
    *,
    title="Test Book",
    use_ncx=False,
    matter: set[str] = frozenset(),
) -> Path:
    """docs: file name -> body html. toc: [(title, href, children)]."""
    manifest = "".join(
        f'<item id="{n}" href="{n}" media-type="application/xhtml+xml"/>' for n in docs
    )
    spine = "".join(f'<itemref idref="{n}"/>' for n in docs)
    if use_ncx:
        manifest += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        spine_attr = ' toc="ncx"'
    else:
        manifest += (
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
        spine_attr = ""
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>
<dc:title>{title}</dc:title><dc:language>en</dc:language><dc:creator>Anon</dc:creator></metadata>
<manifest>{manifest}</manifest><spine{spine_attr}>{spine}</spine></package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        for name, body in docs.items():
            zf.writestr(
                f"OEBPS/{name}", xhtml(body, "frontmatter" if name in matter else "bodymatter")
            )
        if use_ncx:
            zf.writestr(
                "OEBPS/toc.ncx",
                '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"'
                f' version="2005-1"><navMap>{ncx_points(toc)}</navMap></ncx>',
            )
        else:
            zf.writestr(
                "OEBPS/nav.xhtml",
                xhtml(f'<nav epub:type="toc"><h1>Contents</h1>{nav_ol(toc)}</nav>', "frontmatter"),
            )
    return path


def omnibus(path: Path, *, use_ncx=False) -> Path:
    """Two 'books' in one file; book 2's chapters share one file split by anchors."""
    docs = {
        "title.xhtml": "<h1>The Omnibus</h1><p>Copyright nobody.</p>",
        "b1.xhtml": "<h1>Book One</h1><p>Book one title page.</p>",
        "b1c1.xhtml": f"<h2>Chapter 1</h2><p>{para('a', 120)}</p><p>{para('b', 120)}</p>",
        "b1c2.xhtml": f"<h2>Chapter 2</h2><p>{para('c', 90)}</p>",
        "b2.xhtml": "<h1>Book Two</h1><p>Book two title page.</p>",
        "b2text.xhtml": (
            f'<h2 id="c1">Chapter 1</h2><p>{para("d", 200)}</p><p>{para("e", 200)}</p>'
            f"<p>{para('f', 200)}</p>"
            f'<h2 id="c2">Chapter 2</h2><p>Second <span epub:type="pagebreak" title="9"/>'
            f'chapter {para("g", 60)}<a epub:type="noteref" href="#n1">1</a></p>'
        ),
        "about.xhtml": "<h1>About the Author</h1><p>Anon wrote things.</p>",
    }
    toc = [
        ("Title Page", "title.xhtml", []),
        (
            "Book One",
            "b1.xhtml",
            [("Chapter 1", "b1c1.xhtml", []), ("Chapter 2", "b1c2.xhtml", [])],
        ),
        (
            "Book Two",
            "b2.xhtml",
            [("Chapter 1", "b2text.xhtml#c1", []), ("Chapter 2", "b2text.xhtml#c2", [])],
        ),
        ("About the Author", "about.xhtml", []),
    ]
    return build_epub(path, docs, toc, title="The Omnibus", use_ncx=use_ncx)
