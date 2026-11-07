"""Summaries are compiled in reading order and read back through the horizon."""

import json
import re

import httpx
import pytest
from conftest import words
from epub_factory import build_epub, para
from typer.testing import CliRunner

from tome import cli
from tome.answer import recap_pieces
from tome.horizon import Anchor, HorizonReader, resolve_anchor
from tome.llm.client import ChatClient, LLMError
from tome.llm.providers import PRESETS
from tome.pack_writer import BookText, ChapterText, PackWriter, ReadingOrderViolation
from tome.series import Series
from tome.summarize import CHECK_SYSTEM, chunk_passages, summarize_pack

SERIES = Series("t", "T", "public_domain", ("vllm-local",))


def _is_check(request: httpx.Request) -> bool:
    return json.loads(request.content)["messages"][0]["content"] == CHECK_SYSTEM


def _mock_client(handler, check=None) -> ChatClient:
    """``handler`` answers the summary calls. Rollup checks pass, unless ``check`` answers them."""

    def route(request):
        if _is_check(request):
            return check(request) if check else _reply('{"verdicts": []}')
        return handler(request)

    return ChatClient(
        PRESETS["vllm-local"],
        SERIES,
        model="m",
        http=httpx.Client(transport=httpx.MockTransport(route)),
    )


def _reply(text="A summary.", finish="stop", cost=None):
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    if cost is not None:
        usage["cost"] = cost
    return httpx.Response(
        200,
        json={
            "model": "m",
            "choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": usage,
        },
    )


class Recorder:
    """A fake server. Replies name the call, and each prompt is kept for inspection."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.prompts.append(body["messages"][-1]["content"])
        return _reply(f"Reply {len(self.prompts)}.")


def _writer(tmp_path, books=2, chapters=3, name="p.tome") -> PackWriter:
    """Chapter passages hold a unique marker: b<book>c<chapter>marker."""
    w = PackWriter(tmp_path / name, pack_id="t", series_title="T")
    for b in range(1, books + 1):
        chs = [
            ChapterText(f"Ch {c}", [f"b{b}c{c}marker reply a summary whole " + words(20, "w")])
            for c in range(1, chapters + 1)
        ]
        w.add_book(b, BookText(f"Book {b}", chs))
    return w


def _chapter_markers(prompt: str) -> set[tuple[int, int]]:
    return {(int(b), int(c)) for b, c in re.findall(r"b(\d+)c(\d+)marker", prompt)}


def test_chunk_passages_keeps_order_and_limit():
    passages = [words(40, "a"), words(40, "b"), words(40, "c"), words(200, "d"), words(10, "e")]
    chunks = chunk_passages(passages, max_words=100)
    assert [p for c in chunks for p in c] == passages
    assert [len(c) for c in chunks] == [2, 1, 1, 1]


def test_no_prompt_holds_text_from_a_later_chapter(tmp_path):
    server = Recorder()
    w = _writer(tmp_path)
    summarize_pack(w, _mock_client(server), rollup_every=2)
    w.close()
    chapter_order = [(b, c) for b in (1, 2) for c in (1, 2, 3)]
    seen = [m for p in server.prompts if (m := _chapter_markers(p))]
    # Each chapter's text appears exactly once, alone, in reading order.
    assert seen == [{c} for c in chapter_order]


def test_each_chapter_gets_earlier_context_only(tmp_path):
    server = Recorder()
    w = _writer(tmp_path, books=1, chapters=3)
    summarize_pack(w, _mock_client(server), rollup_every=100)
    w.close()
    assert "CHAPTERS SINCE THEN" not in server.prompts[0]
    assert "Reply 1." in server.prompts[1]
    assert "Reply 1." in server.prompts[2] and "Reply 2." in server.prompts[2]


def test_rollups_land_on_checkpoints_and_book_ends(tmp_path):
    w = _writer(tmp_path, books=2, chapters=3)
    stats = summarize_pack(w, _mock_client(Recorder()), rollup_every=2)
    # Book 1 chapter 2 (checkpoint), each book's chapter 3 (book end), book 2 chapter 2.
    rows = w.conn.execute(
        "SELECT kind, max_source_pos FROM rollups ORDER BY max_source_pos, kind DESC"
    ).fetchall()
    w.close()
    assert [(r["kind"], r["max_source_pos"]) for r in rows] == [
        ("story_so_far", 2),
        ("story_so_far", 3),
        ("book", 3),
        ("story_so_far", 5),
        ("story_so_far", 6),
        ("book", 6),
    ]
    assert (stats.chapters, stats.story_so_far, stats.book_recaps) == (6, 4, 2)
    assert stats.llm_calls == 18 and stats.rollup_checks == 6  # each rollup is checked


def test_long_chapter_is_chunked_with_a_running_draft(tmp_path):
    server = Recorder()
    w = PackWriter(tmp_path / "p.tome", pack_id="t", series_title="T")
    passages = [f"part{i} reply " + words(60, "w") for i in range(3)]
    w.add_book(1, BookText("B", [ChapterText("C", passages)]))
    summarize_pack(w, _mock_client(server), chunk_words=70)
    assert w.conn.execute("SELECT count(*) FROM chapter_summaries").fetchone()[0] == 1
    w.close()
    assert "part0" in server.prompts[0] and "part1" not in server.prompts[0]
    assert "part1" in server.prompts[1] and "Reply 1." in server.prompts[1]
    assert "part2" in server.prompts[2] and "Reply 2." in server.prompts[2]


def test_summaries_stay_hidden_until_the_chapter_is_finished(tmp_path):
    path = tmp_path / "p.tome"
    w = PackWriter(path, pack_id="t", series_title="T")
    chapters = [
        ChapterText(f"Ch {c}", ["one " + words(20, "w"), "two " + words(20, "w")]) for c in (1, 2)
    ]
    w.add_book(1, BookText("B", chapters))
    summarize_pack(w, _mock_client(Recorder()), rollup_every=100)
    w.finalize()
    w.close()
    # pos: chapter 1 is 1-2, chapter 2 is 3-4.
    with HorizonReader(path, 1) as r:
        assert r.chapter_summaries() == []
    with HorizonReader(path, 3) as r:
        assert [s["chapter_number"] for s in r.chapter_summaries()] == [1]
        assert r.latest_rollup() is None
    with HorizonReader(path, 4) as r:
        assert r.latest_rollup() is not None


def test_recap_is_latest_rollup_plus_newer_chapters(tmp_path):
    path = tmp_path / "p.tome"
    w = _writer(tmp_path, books=2, chapters=3)
    summarize_pack(w, _mock_client(Recorder()), rollup_every=100)
    w.finalize()
    w.close()
    at = resolve_anchor(path, Anchor.parse("b2 ch2")).pos
    with HorizonReader(path, at) as r:
        pieces = recap_pieces(r)
        assert [p.kind for p in pieces] == ["rollup", "summary", "summary"]
        assert pieces[1].text.startswith("b2 ch1, Ch 1: ")
        assert pieces[2].text.startswith("b2 ch2, Ch 2: ")
        assert max(p.max_source_pos for p in pieces) <= at
        assert r.book_recap(1) is not None
        assert r.book_recap(2) is None  # not finished yet


def test_recap_at_the_very_start_is_empty(tmp_path):
    path = tmp_path / "p.tome"
    w = _writer(tmp_path, books=1, chapters=1)
    summarize_pack(w, _mock_client(Recorder()))
    w.finalize()
    w.close()
    with HorizonReader(path, 0) as r:
        assert recap_pieces(r) == []


def test_max_chapters_stops_after_a_checkpoint(tmp_path):
    w = _writer(tmp_path, books=2, chapters=3)
    stats = summarize_pack(w, _mock_client(Recorder()), max_chapters=2)
    w.close()
    assert (stats.chapters, stats.story_so_far, stats.book_recaps) == (2, 1, 0)


def test_transient_errors_are_retried_then_raised(tmp_path):
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(502, text="bad") if len(calls) == 1 else _reply()

    w = _writer(tmp_path, books=1, chapters=1)
    naps = []
    stats = summarize_pack(w, _mock_client(flaky), sleep=naps.append)
    w.close()
    assert stats.chapters == 1 and naps == [5.0]

    w = _writer(tmp_path, books=1, chapters=1, name="q.tome")
    with pytest.raises(LLMError, match="HTTP 500"):
        summarize_pack(
            w,
            _mock_client(lambda request: httpx.Response(500, text="down")),
            sleep=lambda _s: None,
        )
    w.close()


def test_empty_reply_is_not_stored(tmp_path):
    w = _writer(tmp_path, books=1, chapters=1)
    with pytest.raises(LLMError, match="empty reply"):
        summarize_pack(w, _mock_client(lambda request: _reply("   ")), sleep=lambda _s: None)
    assert w.conn.execute("SELECT count(*) FROM chapter_summaries").fetchone()[0] == 0
    w.close()


def test_usage_and_cost_reach_the_run_record(tmp_path):
    w = _writer(tmp_path, books=1, chapters=1)
    stats = summarize_pack(w, _mock_client(lambda request: _reply(cost=0.5)))
    run = w.conn.execute("SELECT * FROM runs WHERE kind='summaries'").fetchone()
    w.close()
    # One chapter summary, one story so far, one book recap, and a check of each rollup.
    assert stats.cost_usd == 1.5
    assert run["llm_model"] == "m" and run["prompt_version"]
    assert (run["prompt_tokens"], run["completion_tokens"]) == (50, 25)
    assert json.loads(run["stats_json"])["llm_calls"] == 5


def _cut_off_when(condition):
    """A fake server that cuts off any reply whose prompt meets ``condition``."""

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        return _reply("Cut off mid", finish="length") if condition(prompt) else _reply("Whole.")

    return handler


def test_a_cut_off_reply_is_retried_shorter(tmp_path):
    prompts = []

    def handler(request):
        prompts.append(json.loads(request.content)["messages"][-1]["content"])
        return _reply("Cut off mid", finish="length") if len(prompts) == 2 else _reply("Whole.")

    w = _writer(tmp_path, books=1, chapters=1)
    stats = summarize_pack(w, _mock_client(handler))
    texts = [r[0] for r in w.conn.execute("SELECT text FROM rollups WHERE kind='story_so_far'")]
    w.close()
    assert "at most 200 words" in prompts[2] and prompts[2].startswith(prompts[1])
    assert texts == ["Whole."] and stats.truncated == 1 and stats.rollups_skipped == 0


def test_a_cut_off_rollup_is_never_stored_and_recap_still_covers_the_chapters(tmp_path):
    path = tmp_path / "p.tome"
    w = _writer(tmp_path, books=1, chapters=3)
    client = _mock_client(_cut_off_when(lambda p: "story so far" in p or "recap of this book" in p))
    stats = summarize_pack(w, client, rollup_every=2)
    w.finalize()
    assert w.conn.execute("SELECT count(*) FROM rollups").fetchone()[0] == 0
    w.close()
    # Checkpoints at chapters 2 and 3, plus the book recap, each tried twice.
    assert stats.rollups_skipped == 3 and stats.truncated == 6
    with HorizonReader(path, 3) as r:
        assert [p.kind for p in recap_pieces(r)] == ["summary"] * 3


def test_each_rollup_is_built_from_every_chapter_of_its_book(tmp_path):
    """Rewriting the previous rollup instead lost the start of the story in a live run."""
    server = Recorder()
    w = _writer(tmp_path, books=1, chapters=3)
    summarize_pack(w, _mock_client(server), rollup_every=1)
    w.close()
    last = next(p for p in server.prompts if "through BOOK 1, CHAPTER 3" in p)
    # Calls run summary, rollup, summary, rollup, summary: 1, 3 and 5 are the summaries.
    assert all(f"Reply {n}." in last for n in (1, 3, 5))
    assert "Reply 2." not in last and "Reply 4." not in last


def test_later_books_get_earlier_recaps_not_their_chapters(tmp_path):
    prompts = []

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        if "recap of this book" in prompt:
            return _reply("BOOK ONE RECAP.")
        return _reply(f"Summary {len(prompts)}.")

    w = _writer(tmp_path, books=2, chapters=1)
    summarize_pack(w, _mock_client(handler))
    w.close()
    rollup = next(p for p in prompts if "through BOOK 2, CHAPTER 1" in p)
    assert "RECAPS OF EARLIER BOOKS" in rollup and "BOOK ONE RECAP." in rollup
    assert "Summary 1." not in rollup


def test_a_chapter_summary_cut_off_twice_stops_the_run(tmp_path):
    w = _writer(tmp_path, books=1, chapters=1)
    client = _mock_client(_cut_off_when(lambda p: True))
    with pytest.raises(LLMError, match="cut off twice"):
        summarize_pack(w, client)
    assert w.conn.execute("SELECT count(*) FROM chapter_summaries").fetchone()[0] == 0
    w.close()


def test_the_cursor_still_blocks_a_late_write(tmp_path):
    w = _writer(tmp_path, books=1, chapters=1)
    w.cursor = 0
    run = w.start_run("summaries")
    with pytest.raises(ReadingOrderViolation):
        w.add_chapter_summary(chapter_id=1, summary_text="too soon", run_id=run)
    w.close()


# --------------------------------------------------------------------- CLI --


@pytest.fixture
def series_dir(tmp_path, monkeypatch):
    """Run in a directory with series configs and a small EPUB."""
    d = tmp_path / "series"
    d.mkdir()
    (d / "t.toml").write_text(
        'id = "t"\ntitle = "T"\nrights = "public_domain"\nallowed_providers = ["vllm-local"]\n'
    )
    (d / "c.toml").write_text('id = "c"\ntitle = "C"\nallowed_providers = ["vllm-local"]\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _fake_http(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(
        "tome.llm.client.httpx.Client",
        lambda **kw: real(transport=httpx.MockTransport(handler)),
    )


def _book(path):
    docs = {f"c{i}.xhtml": f"<h2>Chapter {i}</h2><p>{para(f't{i}', 300)}</p>" for i in (1, 2)}
    toc = [(f"Chapter {i}", f"c{i}.xhtml", []) for i in (1, 2)]
    build_epub(path, docs, toc, title="Small")


def test_ingest_then_recap(series_dir, monkeypatch):
    _book(series_dir / "b.epub")
    _fake_http(monkeypatch, Recorder())
    run = CliRunner().invoke(
        cli.app,
        ["ingest", "b.epub", "--series", "t", "--out", "o.tome", "--provider", "vllm-local",
         "--model", "m"],
    )  # fmt: skip
    assert run.exit_code == 0, run.output
    assert "2 chapter summaries" in run.output
    assert not (series_dir / "o.tome.partial").exists()
    with HorizonReader(series_dir / "o.tome", 0) as r:
        assert r.manifest()["llm_model"] == "m"
    recap = CliRunner().invoke(cli.app, ["recap", "--pack", "o.tome", "--at", "b1 ch1"])
    assert recap.exit_code == 0 and "Reply 1." in recap.output
    assert "Reply 2." not in recap.output
    book = CliRunner().invoke(
        cli.app, ["recap", "--pack", "o.tome", "--at", "b1 ch1", "--book", "1"]
    )
    assert "No recap of book 1" in book.output


def test_ingest_failure_leaves_no_finished_pack(series_dir, monkeypatch):
    _book(series_dir / "b.epub")
    _fake_http(monkeypatch, lambda request: httpx.Response(500, text="down"))
    monkeypatch.setattr("tome.summarize.RETRY_DELAY_S", 0.0)
    run = CliRunner().invoke(
        cli.app,
        ["ingest", "b.epub", "--series", "t", "--out", "o.tome", "--provider", "vllm-local",
         "--model", "m"],
    )  # fmt: skip
    assert run.exit_code != 0
    assert not (series_dir / "o.tome").exists()


def test_ingest_refuses_a_disallowed_provider_before_reading_the_book(series_dir, monkeypatch):
    def no_network(request):
        raise AssertionError("no request should be made")

    _fake_http(monkeypatch, no_network)
    run = CliRunner().invoke(
        cli.app,
        ["ingest", "missing.epub", "--series", "c", "--out", "o.tome", "--provider", "openrouter",
         "--model", "m"],
    )  # fmt: skip
    assert run.exit_code != 0
    assert "not in the allowed list" in str(run.exception)
    assert not (series_dir / "o.tome.partial").exists()


def test_ingest_will_not_overwrite_without_force(series_dir):
    (series_dir / "o.tome").write_text("existing")
    run = CliRunner().invoke(
        cli.app,
        ["ingest", "b.epub", "--series", "t", "--out", "o.tome", "--provider", "vllm-local"],
    )
    assert run.exit_code != 0
    assert (series_dir / "o.tome").read_text() == "existing"


def test_recap_explains_a_parse_only_pack(tmp_path):
    path = tmp_path / "p.tome"
    w = _writer(tmp_path, books=1, chapters=1)
    w.start_run("parse")
    w.finalize()
    w.close()
    out = CliRunner().invoke(cli.app, ["recap", "--pack", str(path), "--at", "b1 ch1"])
    assert "no summaries" in out.output


def _names_writer(tmp_path) -> PackWriter:
    w = PackWriter(tmp_path / "names.tome", pack_id="t", series_title="T")
    w.add_book(1, BookText("Book", [ChapterText("One", ["Dorothy met a gale of wind."])]))
    return w


def test_unseen_name_regenerates_with_the_name_forbidden(tmp_path):
    prompts = []

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        return _reply("Dorothy met a wind." if "Do not use" in prompt else "Dorothy Gale met.")

    w = _names_writer(tmp_path)
    stats = summarize_pack(w, _mock_client(handler))
    summary = w.conn.execute("SELECT summary_text FROM chapter_summaries").fetchone()[0]
    w.close()
    assert summary == "Dorothy met a wind."
    assert "Do not use these words, which the text has not used at this point: Gale" in prompts[1]
    assert stats.unseen_names == {}
    assert stats.name_retries == 3  # the chapter, the rollup and the recap


def test_name_that_survives_the_retry_is_reported(tmp_path):
    w = _names_writer(tmp_path)
    stats = summarize_pack(w, _mock_client(lambda _r: _reply("Dorothy Gale met.")))
    w.close()
    assert stats.unseen_names == {
        "BOOK 1, CHAPTER 1 (One)": ["Gale"],
        "story so far through BOOK 1, CHAPTER 1 (One)": ["Gale"],
        "recap of Book": ["Gale"],
    }
    assert stats.llm_calls == 8  # 6 summary calls and a check of each rollup


def test_name_used_by_an_earlier_chapter_is_allowed_later(tmp_path):
    w = PackWriter(tmp_path / "later.tome", pack_id="t", series_title="T")
    chapters = [ChapterText("One", ["Dorothy left."]), ChapterText("Two", ["Toto barked."])]
    w.add_book(1, BookText("Book", chapters))
    replies = iter(
        ["Dorothy left, and Toto barked.", "Dorothy left.", "Dorothy left, and Toto barked."]
    )

    def handler(_request):
        return _reply(next(replies, "Dorothy left, and Toto barked."))

    stats = summarize_pack(w, _mock_client(handler))
    w.close()
    # The first reply names Toto a chapter early, so it is regenerated. Later ones may name Toto.
    assert stats.name_retries == 1
    assert stats.unseen_names == {}


# ------------------------------------------------------------- rollup check --


def _spell_writer(tmp_path) -> PackWriter:
    w = PackWriter(tmp_path / "spell.tome", pack_id="t", series_title="T")
    text = "b1c1marker She plans to cast a spell at noon, and he runs."
    w.add_book(1, BookText("Book 1", [ChapterText("Ch 1", [text])]))
    return w


def _verdicts(wrong):
    """A fake check: "no" for each numbered sentence that ``wrong`` picks out."""

    def check(request):
        summary = json.loads(request.content)["messages"][-1]["content"].rsplit("SUMMARY:\n")[1]
        verdicts = []
        for line in summary.splitlines():
            n, _, sentence = line.partition(". ")
            bad = wrong(sentence)
            verdicts.append({"n": int(n), "supported": "no" if bad else "yes", "why": "plan only"})
        return _reply(json.dumps({"verdicts": verdicts}))

    return check


def _rollup_server(prompts, fix="She plans a spell."):
    """Rollups claim a deed; a request to fix a sentence gets ``fix``."""

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        if "This sentence from a summary" in prompt:
            return _reply(fix)
        if "CHAPTERS OF THIS BOOK SO FAR" in prompt or "recap of this book" in prompt:
            return _reply("She casts a spell. He runs.")
        return _reply("She plans a spell. He runs.")

    return handler


def test_an_unsupported_sentence_is_fixed_in_place(tmp_path):
    prompts, checks = [], []
    verdicts = _verdicts(lambda x: "casts" in x)

    def check(request):
        checks.append(json.loads(request.content)["messages"][-1]["content"])
        return verdicts(request)

    w = _spell_writer(tmp_path)
    stats = summarize_pack(w, _mock_client(_rollup_server(prompts), check))
    texts = [r[0] for r in w.conn.execute("SELECT text FROM rollups ORDER BY rollup_id")]
    w.close()
    assert texts == ["She plans a spell. He runs."] * 2
    fix = next(p for p in prompts if "This sentence from a summary" in p)
    assert "“She casts a spell.”" in fix and "The problem: plan only" in fix
    assert (stats.rollup_retries, stats.rollup_fixed, stats.unsupported) == (2, 2, {})
    assert stats.fixes["recap of Book 1"] == [["She casts a spell.", "She plans a spell."]]
    # Each rollup and each fix is checked, against the chapter summaries, never the text.
    assert stats.rollup_checks == 4
    assert all("b1c1marker" not in c and "She plans a spell. He runs." in c for c in checks)


def test_a_fix_that_fails_its_check_is_dropped_and_reported(tmp_path):
    w = _spell_writer(tmp_path)
    server = _rollup_server([], fix="She casts a spell at noon.")
    stats = summarize_pack(w, _mock_client(server, _verdicts(lambda x: "casts" in x)))
    texts = [r[0] for r in w.conn.execute("SELECT text FROM rollups ORDER BY rollup_id")]
    w.close()
    assert texts == ["She casts a spell. He runs."] * 2
    assert stats.rollup_fixed == 0
    assert stats.unsupported == {
        "story so far through BOOK 1, CHAPTER 1 (Ch 1)": ["She casts a spell."],
        "recap of Book 1": ["She casts a spell."],
    }


def test_a_fix_with_a_name_the_text_has_not_used_is_refused(tmp_path):
    w = _spell_writer(tmp_path)
    server = _rollup_server([], fix="Mombi plans a spell.")
    stats = summarize_pack(w, _mock_client(server, _verdicts(lambda x: "casts" in x)))
    w.close()
    assert stats.rollup_fixed == 0 and len(stats.unsupported) == 2


def test_a_supported_rollup_is_left_alone(tmp_path):
    prompts = []
    w = _spell_writer(tmp_path)
    stats = summarize_pack(w, _mock_client(_rollup_server(prompts), _verdicts(lambda x: False)))
    w.close()
    assert stats.rollup_retries == 0 and stats.rollup_checks == 2
    assert not any("This sentence from a summary" in p for p in prompts)


def test_a_failed_check_keeps_the_rollup(tmp_path):
    w = _spell_writer(tmp_path)
    stats = summarize_pack(w, _mock_client(_rollup_server([]), lambda _r: _reply("not json")))
    n = w.conn.execute("SELECT count(*) FROM rollups").fetchone()[0]
    w.close()
    assert n == 2 and stats.rollup_check_errors == 2 and stats.rollup_retries == 0
