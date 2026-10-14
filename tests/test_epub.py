import pytest
from epub_factory import build_epub, omnibus, para

from tome.epub.parse import Layout, parse_epub
from tome.epub.passages import MAX_WORDS, split_passages
from tome.text import word_count


@pytest.mark.parametrize("use_ncx", [False, True])
def test_single_book_by_default_with_hint(tmp_path, use_ncx):
    r = parse_epub(omnibus(tmp_path / "o.epub", use_ncx=use_ncx), Layout())
    assert len(r.books) == 1
    assert [c.title for c in r.books[0].chapters] == ["Chapter 1", "Chapter 2"] * 2
    assert r.hint and "split" in r.hint
    text = " ".join(p for c in r.books[0].chapters for p in c.passages)
    assert "title page" not in text and "Anon wrote" not in text  # matter stripped
    assert "Chapter 1" not in text  # headings are not passage text


@pytest.mark.parametrize("use_ncx", [False, True])
def test_omnibus_split_by_nested_toc(tmp_path, use_ncx):
    r = parse_epub(omnibus(tmp_path / "o.epub", use_ncx=use_ncx), Layout(split="toc"))
    assert [b.title for b in r.books] == ["Book One", "Book Two"]
    b2 = r.books[1]
    assert [c.title for c in b2.chapters] == ["Chapter 1", "Chapter 2"]
    # Anchored chapters in one file are cut at the anchor.
    assert "gw0" not in " ".join(b2.chapters[0].passages)
    assert b2.chapters[1].passages[0].startswith("Second chapter gw0")
    # Page-break markers and note references are dropped from the text.
    assert "9" not in b2.chapters[1].passages[0].split()[:3]
    assert not b2.chapters[1].passages[0].rstrip(".").endswith("1")


def test_layout_titles_and_manual_split(tmp_path):
    path = omnibus(tmp_path / "o.epub")
    r = parse_epub(path, Layout(split="toc", titles=["First", "Second"]))
    assert [b.title for b in r.books] == ["First", "Second"]

    manual = Layout(
        split="manual",
        books=[{"title": "A", "start": "^Book One$"}, {"title": "B", "start": "^Book Two$"}],
    )
    r = parse_epub(path, manual)
    assert [(b.title, len(b.chapters)) for b in r.books] == [("A", 2), ("B", 2)]


def test_layout_sidecar_file_is_picked_up(tmp_path):
    path = omnibus(tmp_path / "o.epub")
    (tmp_path / "o.layout.toml").write_text('split = "toc"\nexclude = ["^Chapter 2$"]\n')
    r = parse_epub(path)
    assert [len(b.chapters) for b in r.books] == [1, 1]


def test_excluding_a_book_group_drops_its_chapters(tmp_path):
    path = omnibus(tmp_path / "o.epub")
    full = parse_epub(path, Layout(split="toc"))
    r = parse_epub(path, Layout(split="toc", exclude=["^Book Two$"]))
    assert [(b.title, len(b.chapters)) for b in r.books] == [("Book One", 2)]
    # Book One still ends where Book Two starts.
    assert r.books[0].chapters == full.books[0].chapters


def test_bad_layout(tmp_path):
    (tmp_path / "x.toml").write_text('split = "magic"\n')
    with pytest.raises(ValueError):
        Layout.load(tmp_path / "x.toml")


def test_no_toc_falls_back_to_spine(tmp_path):
    docs = {f"c{i}.xhtml": f"<h1>Part {i}</h1><p>{para(str(i), 30)}</p>" for i in range(3)}
    r = parse_epub(build_epub(tmp_path / "n.epub", docs, []), Layout())
    assert [c.title for c in r.books[0].chapters] == ["Part 0", "Part 1", "Part 2"]
    assert r.warnings


def test_passage_sizes():
    paragraphs = [para(f"p{i}", n) for i, n in enumerate([40, 60, 500, 30, 30, 10, 260, 5])]
    passages = split_passages(paragraphs)
    sizes = [word_count(p) for p in passages]
    assert all(s <= MAX_WORDS for s in sizes)
    assert all(s >= 150 for s in sizes)
    assert sum(sizes) == sum(word_count(p) for p in paragraphs)


def test_short_chapter_is_one_passage():
    assert len(split_passages(["Just a few words."])) == 1


# --- Real public-domain corpus (uv run tome corpus fetch) ----------------------------------


@pytest.mark.corpus
def test_monte_cristo_parses_sensibly(monte_cristo_epub):
    r = parse_epub(monte_cristo_epub, Layout())
    assert len(r.books) == 1
    chapters = r.books[0].chapters
    assert len(chapters) == 117
    assert chapters[0].title.endswith("Marseilles—The Arrival")
    assert chapters[0].passages[0].startswith("On the 24th of February, 1815")
    assert chapters[-1].passages[-1].rstrip("”’ ").endswith("Wait and hope (Fac et spera)!")
    sizes = [word_count(p) for c in chapters for p in c.passages]
    assert 1400 < len(sizes) < 2000 and max(sizes) <= MAX_WORDS
    assert sum(s < 150 for s in sizes) <= 5
    all_text = " ".join(p for c in chapters for p in c.passages)
    assert "Standard Ebooks" not in all_text and "Uncopyright" not in all_text


@pytest.mark.corpus
def test_gutenberg_edition_splits_into_volumes(corpus_dir):
    path = corpus_dir / "monte-cristo-gutenberg.epub"
    if not path.exists():
        pytest.skip("run: uv run tome corpus fetch monte-cristo-gutenberg")
    r = parse_epub(path, Layout(split="toc"))
    assert [b.title for b in r.books] == [
        f"VOLUME {n}" for n in ("ONE", "TWO", "THREE", "FOUR", "FIVE")
    ]
    assert sum(len(b.chapters) for b in r.books) == 117
    last = r.books[-1].chapters[-1].passages[-1]
    assert "Gutenberg" not in last and "Wait and hope" in last
