import json

import pytest

from conftest import REPO
from tome.answer import answer
from tome.epub.parse import Layout, parse_epub
from tome.evals.runner import (
    CaseError,
    contains_phrase,
    format_report,
    load_cases,
    run_eval,
)
from tome.horizon import HorizonReader

PUBLIC = REPO / "evals" / "public" / "monte-cristo"
TEMPLATES = REPO / "evals" / "templates" / "private"


def test_public_cases_load():
    cases = load_cases(PUBLIC)
    kinds = {c.kind for c in cases}
    assert kinds == {"spoiler", "coverage"}
    assert len([c for c in cases if c.kind == "spoiler"]) >= 10
    assert all(c.series == "monte-cristo" for c in cases)


def test_private_templates_are_valid_case_files(tmp_path):
    for f in TEMPLATES.glob("*.jsonl"):
        target = tmp_path / f.name.replace(".template", "")
        target.write_text(f.read_text())
        assert load_cases(target), f


def test_end_to_end_on_stub_pack(stub_pack):
    report = run_eval(stub_pack, load_cases(PUBLIC))
    assert report.leak_rate == 0.0
    assert report.coverage_score == 1.0
    # The stub plants two observations with invented quotes; they were dropped.
    assert report.quotes.candidates == 13 and report.quotes.dropped == 2
    assert report.quotes.stored == report.quotes.stored_verified == 11
    text = format_report(report)
    assert "Leak rate:        0.0%" in text
    json.dumps(report.to_json())


def test_runner_catches_a_leaky_answerer(stub_pack):
    """Meta-test: an answerer that ignores the horizon must register leaks."""

    def leaky(reader, question):
        with HorizonReader(stub_pack, 10_000) as everything:
            return answer(everything, question)

    report = run_eval(stub_pack, load_cases(PUBLIC), answerer=leaky)
    assert report.leak_rate > 0.5
    leaked = {r.id for r in report.spoiler if not r.passed}
    assert {"mc-s05-busoni-before", "mc-s07-andrea-before-benedetto"} <= leaked
    assert all(r.hard_violation for r in report.spoiler if not r.passed)


def test_other_series_cases_are_skipped(stub_pack, tmp_path):
    f = tmp_path / "x.spoiler.jsonl"
    f.write_text(
        '{"id": "x", "series": "cradle", "horizon": "b1 ch1", "question": "q",'
        ' "must_not_include": ["y"]}\n'
    )
    report = run_eval(stub_pack, load_cases(f))
    assert report.skipped == ["x"] and report.spoiler == []


@pytest.mark.parametrize(
    "line,err",
    [
        ('{"id": "a", "series": "s", "horizon": "b1 ch1", "question": "q"}', "needs"),
        (
            '{"id": "a", "series": "s", "horizon": "chapter 1", "question": "q",'
            ' "must_not_include": ["x"]}',
            "expected something",
        ),
        (
            '{"id": "a", "series": "s", "horizon": "b1 ch1", "question": "q",'
            ' "must_not_include": []}',
            "non-empty",
        ),
        ("not json", "Expecting value"),
    ],
)
def test_bad_cases_are_rejected(tmp_path, line, err):
    f = tmp_path / "bad.jsonl"
    f.write_text(line + "\n")
    with pytest.raises((CaseError, ValueError), match=err):
        load_cases(f)


def test_phrase_matching():
    assert contains_phrase("He is the Count of Monte Cristo.", "count of monte cristo")
    assert contains_phrase("Dantes", "Dantès")
    assert not contains_phrase("an account of the voyage", "count")
    assert contains_phrase("she was his fiancée", "betrothed|fiancée")


# --- Validate the public cases against the real text -------------------------------------


@pytest.fixture(scope="module")
def real_passages(monte_cristo_epub):
    book = parse_epub(monte_cristo_epub, Layout()).books[0]
    return [(n, p) for n, ch in enumerate(book.chapters, start=1) for p in ch.passages]


@pytest.mark.corpus
def test_public_spoiler_phrases_do_not_occur_before_the_horizon(real_passages):
    """Each must-not phrase must be unknowable at the horizon (alongside the subject)."""
    for case in load_cases(PUBLIC):
        if case.kind != "spoiler":
            continue
        before = [p for n, p in real_passages if n <= case.anchor.chapter]
        after = [p for n, p in real_passages if n > case.anchor.chapter]
        if case.subject_terms:
            before = [p for p in before if any(contains_phrase(p, t) for t in case.subject_terms)]
        for phrase in case.phrases:
            early = [p[:120] for p in before if contains_phrase(p, phrase)]
            assert not early, f"{case.id}: {phrase!r} already appears before the horizon: {early}"
        # Paraphrase lists are fine, but at least one phrase must be a real later fact.
        assert any(contains_phrase(p, ph) for ph in case.phrases for p in after), case.id


@pytest.mark.corpus
def test_public_coverage_facts_are_knowable_at_the_horizon(real_passages):
    for case in load_cases(PUBLIC):
        if case.kind != "coverage":
            continue
        before = [p for n, p in real_passages if n <= case.anchor.chapter]
        for fact in case.phrases:
            assert any(contains_phrase(p, fact) for p in before), f"{case.id}: {fact!r}"
