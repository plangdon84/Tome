"""Stage A model comparison: what the judge sees, and how its verdicts are scored."""

import json

import httpx
from conftest import words

from tome.compare import Target, format_report, judge, judge_items, judge_pack, score_pack
from tome.llm.client import ChatClient
from tome.llm.providers import PRESETS
from tome.pack_writer import BookText, ChapterText, PackWriter
from tome.series import Series
from tome.summarize import summarize_pack

SERIES = Series("t", "T", "public_domain", ("vllm-local",))


def _client(handler, model="judge") -> ChatClient:
    return ChatClient(
        PRESETS["vllm-local"],
        SERIES,
        model=model,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _reply(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "m",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def _pack(tmp_path, books=2, chapters=3):
    """Summaries name their chapter ("Summary of b1c2."); the text holds a marker."""
    w = PackWriter(tmp_path / "p.tome", pack_id="t", series_title="T")
    for b in range(1, books + 1):
        chs = [
            ChapterText(f"Ch {c}", [f"text{b}x{c} " + words(20, "w")])
            for c in range(1, chapters + 1)
        ]
        w.add_book(b, BookText(f"Book {b}", chs))

    def server(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        marker = prompt.rsplit("TEXT OF ", 1)[-1]
        found = [m for m in ("1x1 1x2 1x3 2x1 2x2 2x3".split()) if f"text{m}" in marker]
        return _reply(f"Summary of b{found[0].replace('x', 'c')}." if found else "A rollup.")

    summarize_pack(w, _client(server, "m"), rollup_every=100)
    w.finalize()
    w.close()
    return tmp_path / "p.tome"


def test_items_hold_only_earlier_inputs(tmp_path):
    items = {i.key: i for i in judge_items(_pack(tmp_path))}
    assert list(items) == [
        "b1-ch1", "b1-ch2", "b1-ch3", "story-b1-ch3", "recap-b1",
        "b2-ch1", "b2-ch2", "b2-ch3", "story-b2-ch3", "recap-b2",
    ]  # fmt: skip
    ch = items["b1-ch2"]
    assert ch.text == "Summary of b1c2."
    assert "text1x2" in ch.inputs and "Summary of b1c1." in ch.inputs
    assert "text1x1" not in ch.inputs and "text1x3" not in ch.inputs
    # Book 2 starts from the recap of book 1, not its chapter summaries.
    first = items["b2-ch1"]
    assert "RECAPS OF EARLIER BOOKS" in first.inputs and "Summary of b1c" not in first.inputs
    # A rollup is judged against the summaries it was built from, never the text.
    story = items["story-b2-ch3"]
    assert "Summary of b2c3." in story.inputs and "text2x" not in story.inputs
    assert "Summary of b1c" not in items["recap-b2"].inputs


def test_judge_keeps_only_real_sentences_once(tmp_path):
    item = judge_items(_pack(tmp_path))[0]
    flags = [
        {"sentence": "Summary of b1c1.", "problem": "contradicted", "reason": "r"},
        {"sentence": "Summary of b1c1.", "problem": "unsupported", "reason": "again"},
        {"sentence": "Something the summary never said.", "problem": "unsupported", "reason": ""},
    ]
    j = judge(_client(lambda _r: _reply(json.dumps({"flags": flags}))), item)
    assert j.sentences == 1
    assert [f["problem"] for f in j.flags] == ["contradicted"]


def test_judgments_are_cached(tmp_path):
    pack = _pack(tmp_path)
    calls = []

    def server(request):
        calls.append(request)
        return _reply('{"flags": []}')

    cache = tmp_path / "j.json"
    first = judge_pack(_client(server), pack, cache)
    n = len(calls)
    assert n == len(first) == 10
    again = judge_pack(_client(server), pack, cache)
    assert len(calls) == n and [j.key for j in again] == [j.key for j in first]
    judge_pack(_client(server, model="other-judge"), pack, cache)
    assert len(calls) == 2 * n


def test_score_and_report(tmp_path):
    pack = _pack(tmp_path)
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        json.dumps({"id": "s1", "series": "t", "horizon": "b1 ch1", "question": "What has "
                    "happened so far?", "must_not_include": ["b1c2"]}) + "\n"
        + json.dumps({"id": "c1", "series": "t", "horizon": "b1 ch2", "question": "What has "
                      "happened so far?", "expected_facts": ["b1c2"]}) + "\n"
    )  # fmt: skip

    def server(request):
        summary = json.loads(request.content)["messages"][-1]["content"].rsplit("SUMMARY:\n")[-1]
        flags = [{"sentence": summary, "problem": "contradicted", "reason": "wrong"}]
        return _reply(json.dumps({"flags": flags if "b1c2" in summary else []}))

    judgments = judge_pack(_client(server), pack, tmp_path / "j.json")
    s = score_pack(Target("t", "t", (), str(cases)), "m", pack, judgments)
    assert (s.leaks, s.spoiler_cases, s.coverage_full, s.coverage_cases) == (0, 1, 1, 1)
    assert s.chapters == 6 and s.problems("contradicted") == 1
    assert s.support_rate("chapter") == 5 / 6 and s.support_rate("book") == 1.0
    report = format_report([s], "judge")
    assert "| Spoiler leaks | 0/1 |" in report
    assert "**contradicted** (b1-ch2): “Summary of b1c2.” wrong" in report
