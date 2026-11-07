"""Stage A of the model-size comparison: public domain, automated (DECISIONS.md §12).

For each model, compile summary packs of the public-domain targets through
OpenRouter, then score them mechanically:

- the spoiler and coverage evals, run against what the app would show;
- a support check: a larger judge model reads each summary next to the inputs
  it was written from and flags sentences those inputs don't support;
- the compiler's own warnings (names the text hasn't used, cut-off replies).

Summaries carry no quotes, so the quote check has nothing to measure until the
Phase 2 observations exist. It is still reported, as "n/a".

Everything lands in one output directory: a pack per (target, model),
``judgments/`` (cached, so a rerun only pays for what is missing),
``results.json`` and ``report.md``.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tome.evals.runner import load_cases, run_eval
from tome.horizon import HorizonReader
from tome.llm.client import ChatClient, LLMError
from tome.series import Series

SMALL_MODEL = "qwen/qwen-2.5-7b-instruct"  # the pod's Qwen/Qwen2.5-7B-Instruct
LARGE_MODEL = "qwen/qwen-2.5-72b-instruct"  # the ~70B tier, same family
# Open-weight, much larger than both, and from another family, so it doesn't
# share their blind spots.
JUDGE_MODEL = "deepseek/deepseek-v3.2"
JUDGE_PROMPT_VERSION = "support-v1"
JUDGE_MAX_TOKENS = 2000


@dataclass(frozen=True)
class Target:
    name: str
    series: str
    epubs: tuple[str, ...]
    cases: str
    max_chapters: int | None = None


TARGETS = {
    t.name: t
    for t in [
        # Books 1-2: book 2 holds the Tip = Ozma reveal, and book 1's recap is
        # the carry-over a book 2 summary starts from. Most cases are in book 1.
        Target("oz", "oz", ("corpus/oz-1.epub", "corpus/oz-2.epub"), "evals/public/oz"),
        # Chapters 1-34 so that the persona chapters (23-34) have their real
        # rolling context.
        Target(
            "monte-cristo",
            "monte-cristo",
            ("corpus/monte-cristo.epub",),
            "evals/public/monte-cristo",
            max_chapters=34,
        ),
    ]
}

PROBLEMS = ("contradicted", "unsupported", "speculation")
JUDGE_SYSTEM = """You check summaries written for a spoiler-safe reading companion. You are \
given the INPUTS a summary was written from and the SUMMARY itself.

Flag every sentence of the summary that has one of these problems:
- contradicted: the inputs say otherwise (a wrong name, event, place, order or relation).
- unsupported: the inputs don't say it. This includes anything you recognise from your own \
knowledge of the book, such as later events, real names or hidden identities the inputs \
haven't given.
- speculation: it guesses at secrets, motives or what will happen, or hints that something \
will matter later, beyond what the inputs state.

Judge only against the inputs, never against what you remember of the book. Paraphrase, \
compression and leaving things out are fine. Flag a sentence once, with its most serious \
problem, copying it exactly. If nothing is wrong, return an empty list."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sentence": {"type": "string"},
                    "problem": {"type": "string", "enum": list(PROBLEMS)},
                    "reason": {"type": "string"},
                },
                "required": ["sentence", "problem", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["flags"],
    "additionalProperties": False,
}

_SENTENCE = re.compile(r"(?<=[.!?])[\"”’']?\s+(?=[\"“‘'(]?[A-Z])")


def sentences(text: str) -> list[str]:
    return [s for s in (x.strip() for x in _SENTENCE.split(text.strip())) if s]


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


# ------------------------------------------------------------- the items --


@dataclass
class Item:
    """One summary to judge, with the inputs it was written from."""

    key: str  # stable across runs: "b1-ch3", "story-b1-ch5", "recap-b1"
    kind: str  # chapter | story_so_far | book
    book: int
    chapter: int
    text: str
    inputs: str


def judge_items(pack: str | Path) -> list[Item]:
    """Every summary and rollup in ``pack``, each with its inputs.

    A chapter summary is judged against that chapter's text, the book's earlier
    chapter summaries and the recaps of earlier books: what the summarizer had,
    give or take its rolling context. A rollup is judged against the chapter
    summaries it was built from, so an error is charged where it was made.
    """
    with HorizonReader(pack, _max_pos(pack)) as r:
        chapters = r.query(
            "SELECT c.chapter_id, c.number, c.title, b.number AS book, s.summary_text"
            " FROM h_chapters c JOIN books b USING (book_id)"
            " JOIN h_chapter_summaries s USING (chapter_id) ORDER BY c.start_pos"
        )
        passages: dict[int, list[str]] = {}
        for p in r.query("SELECT chapter_id, text FROM h_passages ORDER BY pos"):
            passages.setdefault(p["chapter_id"], []).append(p["text"])
        rollups = {
            (row["kind"], row["through_chapter_id"]): row["text"]
            for row in r.query("SELECT kind, through_chapter_id, text FROM h_rollups")
        }
    items: list[Item] = []
    recaps: list[str] = []  # earlier books' recaps, as the summarizer saw them
    book_summaries: list[str] = []
    book = None
    for ch in chapters:
        if ch["book"] != book:
            book, book_summaries = ch["book"], []
        earlier = []
        if recaps:
            earlier.append("RECAPS OF EARLIER BOOKS:\n" + "\n\n".join(recaps))
        if book_summaries:
            earlier.append("EARLIER CHAPTERS OF THIS BOOK:\n" + "\n\n".join(book_summaries))
        text = "\n\n".join(passages.get(ch["chapter_id"], []))
        items.append(
            Item(
                f"b{book}-ch{ch['number']}",
                "chapter",
                book,
                ch["number"],
                ch["summary_text"],
                "\n\n".join([*earlier, f"TEXT OF CHAPTER {ch['number']} ({ch['title']}):\n{text}"]),
            )
        )
        book_summaries.append(f"Chapter {ch['number']}: {ch['summary_text']}")
        built_from = "\n\n".join(
            ([f"RECAPS OF EARLIER BOOKS:\n{chr(10).join(recaps)}"] if recaps else [])
            + ["CHAPTER SUMMARIES, IN ORDER:\n" + "\n\n".join(book_summaries)]
        )
        story = rollups.get(("story_so_far", ch["chapter_id"]))
        if story:
            key = f"story-b{book}-ch{ch['number']}"
            items.append(Item(key, "story_so_far", book, ch["number"], story, built_from))
        recap = rollups.get(("book", ch["chapter_id"]))
        if recap:
            only_book = "CHAPTER SUMMARIES, IN ORDER:\n" + "\n\n".join(book_summaries)
            items.append(Item(f"recap-b{book}", "book", book, ch["number"], recap, only_book))
            recaps.append(recap)
    return items


def _max_pos(pack: str | Path) -> int:
    with HorizonReader(pack, 0) as r:
        return r.one("SELECT max(end_pos) AS m FROM books")["m"] or 0


# ----------------------------------------------------------- the judging --


@dataclass
class Judgment:
    key: str
    kind: str
    book: int
    chapter: int
    sentences: int
    flags: list[dict]
    error: str | None = None


def judge(client: ChatClient, item: Item) -> Judgment:
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": f"INPUTS:\n{item.inputs}\n\nSUMMARY:\n{item.text}"},
    ]
    n = len(sentences(item.text))
    try:
        out = client.structured(
            messages, JUDGE_SCHEMA, name="support_check", purpose="support_check",
            max_tokens=JUDGE_MAX_TOKENS,
        )  # fmt: skip
    except LLMError as exc:
        return Judgment(item.key, item.kind, item.book, item.chapter, n, [], error=str(exc))
    flags, seen = [], set()
    for flag in out["flags"]:
        sentence = flag["sentence"].strip()
        if sentence and sentence not in seen and _norm(sentence) in _norm(item.text):
            seen.add(sentence)
            flags.append({**flag, "sentence": sentence})
    return Judgment(item.key, item.kind, item.book, item.chapter, n, flags[:n])


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[“”]", '"', re.sub(r"[‘’]", "'", text)).split())


def judge_pack(client: ChatClient, pack: Path, cache: Path, *, workers: int = 8) -> list[Judgment]:
    """Judge every item of ``pack``, reusing judgments cached in ``cache`` (a JSON file)."""
    done = {}
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved.get("prompt_version") == JUDGE_PROMPT_VERSION and saved["judge"] == client.model:
            done = {j["key"]: Judgment(**j) for j in saved["judgments"] if not j.get("error")}
    items = judge_items(pack)
    todo = [i for i in items if i.key not in done]
    with ThreadPoolExecutor(workers) as pool:
        for j in pool.map(lambda i: judge(client, i), todo):
            done[j.key] = j
    out = [done[i.key] for i in items]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps(
            {
                "judge": client.model,
                "prompt_version": JUDGE_PROMPT_VERSION,
                "judgments": [asdict(j) for j in out],
            },
            indent=1,
            ensure_ascii=False,
        )
    )
    return out


# ------------------------------------------------------------ the scores --


@dataclass
class Score:
    target: str
    model: str
    pack: str
    chapters: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    truncated: int = 0
    rollups_skipped: int = 0
    name_retries: int = 0
    unseen_names: dict[str, list[str]] = field(default_factory=dict)
    leaks: int = 0
    spoiler_cases: int = 0
    leaked: list[str] = field(default_factory=list)
    coverage: float | None = None
    coverage_full: int = 0
    coverage_cases: int = 0
    coverage_misses: dict[str, list[str]] = field(default_factory=dict)
    quote_check_pass_rate: float | None = None
    sentences: dict[str, int] = field(default_factory=dict)  # per summary kind
    flags: dict[str, dict[str, int]] = field(default_factory=dict)  # kind -> problem -> n
    judge_errors: int = 0
    flagged: list[dict] = field(default_factory=list)

    def support_rate(self, kind: str | None = None) -> float | None:
        kinds = [kind] if kind else list(self.sentences)
        total = sum(self.sentences.get(k, 0) for k in kinds)
        bad = sum(sum(self.flags.get(k, {}).values()) for k in kinds)
        return None if not total else 1 - bad / total

    def problems(self, problem: str) -> int:
        return sum(f.get(problem, 0) for f in self.flags.values())


def score_pack(target: Target, model: str, pack: Path, judgments: Sequence[Judgment]) -> Score:
    with HorizonReader(pack, 0) as r:
        run = r.one("SELECT stats_json FROM runs WHERE kind = 'summaries'")
    stats = json.loads(run["stats_json"] or "{}")
    s = Score(target.name, model, str(pack))
    for name in (
        "chapters", "llm_calls", "prompt_tokens", "completion_tokens", "cost_usd",
        "truncated", "rollups_skipped", "name_retries", "unseen_names",
    ):  # fmt: skip
        setattr(s, name, stats.get(name, getattr(s, name)))
    report = run_eval(pack, load_cases(target.cases))
    s.spoiler_cases = len(report.spoiler)
    s.leaked = [r.id for r in report.spoiler if not r.passed]
    s.leaks = len(s.leaked)
    s.coverage = report.coverage_score
    s.coverage_cases = len(report.coverage)
    s.coverage_full = sum(r.passed for r in report.coverage)
    s.coverage_misses = {r.id: r.misses for r in report.coverage if r.misses}
    s.quote_check_pass_rate = report.quotes.pass_rate
    for j in judgments:
        if j.error:
            s.judge_errors += 1
            continue
        s.sentences[j.kind] = s.sentences.get(j.kind, 0) + j.sentences
        per = s.flags.setdefault(j.kind, {})
        for f in j.flags:
            per[f["problem"]] = per.get(f["problem"], 0) + 1
            s.flagged.append({"where": j.key, **f})
    return s


# --------------------------------------------------------------- the run --


def build_pack(
    target: Target,
    client: ChatClient,
    out: Path,
    *,
    max_chapters: int | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> None:
    """A summary pack for ``target``, written to ``out`` only once it is complete."""
    from tome.epub.parse import Layout, parse_epub
    from tome.pack_writer import PackWriter
    from tome.summarize import summarize_pack

    series = client.series
    results = [(Path(e), parse_epub(Path(e), Layout.for_epub(Path(e)))) for e in target.epubs]
    partial = out.with_name(out.name + ".partial")
    w = PackWriter(partial, pack_id=series.id, series_title=series.title, overwrite=True)
    try:
        w.add_parsed(results)
        limit = max_chapters or target.max_chapters
        summarize_pack(w, client, max_chapters=limit, log=log)
        w.finalize(llm_model=client.model)
    finally:
        w.close()
    partial.replace(out)


def run_comparison(
    out_dir: Path,
    *,
    targets: Sequence[str],
    models: Sequence[str],
    judge_model: str,
    make_client: Callable[[Series, str], ChatClient],
    max_chapters: int | None = None,
    log: Callable[[str], None] = print,
) -> list[Score]:
    """Build (or reuse) every pack, judge it, score it, and write the report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def say(msg: str) -> None:
        with lock:
            log(msg)

    def one(target: Target, model: str) -> Score:
        series = Series.find(target.series)
        pack = out_dir / f"{target.name}--{slug(model)}.tome"
        if pack.exists():
            say(f"{target.name} {model}: reusing {pack}")
        else:
            client = make_client(series, model)
            try:
                build_pack(
                    target, client, pack, max_chapters=max_chapters,
                    log=lambda m: say(f"{target.name} {model}: {m}"),
                )  # fmt: skip
            finally:
                client.close()
        judge_client = make_client(series, judge_model)
        try:
            cache = out_dir / "judgments" / f"{target.name}--{slug(model)}.json"
            judgments = judge_pack(judge_client, pack, cache)
            judge_cost = judge_client.usage.cost_usd
        finally:
            judge_client.close()
        say(f"{target.name} {model}: judged {len(judgments)} summaries (${judge_cost:.4f})")
        return score_pack(target, model, pack, judgments)

    jobs = [(TARGETS[t], m) for t in targets for m in models]
    with ThreadPoolExecutor(len(jobs)) as pool:
        scores = list(pool.map(lambda job: one(*job), jobs))
    (out_dir / "results.json").write_text(
        json.dumps(
            {"judge": judge_model, "scores": [asdict(s) for s in scores]},
            indent=1,
            ensure_ascii=False,
        )
    )
    (out_dir / "report.md").write_text(format_report(scores, judge_model))
    return scores


# ------------------------------------------------------------ the report --


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def format_report(scores: Sequence[Score], judge_model: str) -> str:
    lines = [
        "# Model comparison, Stage A (public domain, automated)",
        "",
        f"Support check judge: `{judge_model}` (prompt `{JUDGE_PROMPT_VERSION}`). "
        "Support = share of summary sentences the judge did not flag.",
        "",
    ]
    for target in dict.fromkeys(s.target for s in scores):
        rows = [s for s in scores if s.target == target]
        lines += [
            f"## {target}",
            "",
            "| | " + " | ".join(f"`{s.model}`" for s in rows) + " |",
            "|---|" + "---|" * len(rows),
        ]

        def row(label: str, fn, rows=rows, lines=lines) -> None:
            lines.append(f"| {label} | " + " | ".join(fn(s) for s in rows) + " |")

        row("Chapters summarized", lambda s: str(s.chapters))
        row("Spoiler leaks", lambda s: f"{s.leaks}/{s.spoiler_cases}")
        row("Coverage", lambda s: f"{_pct(s.coverage)} ({s.coverage_full}/{s.coverage_cases} full)")
        row("Quote-check pass", lambda s: _pct(s.quote_check_pass_rate))
        row("Support, chapter summaries", lambda s: _pct(s.support_rate("chapter")))
        row("Support, story so far", lambda s: _pct(s.support_rate("story_so_far")))
        row("Support, book recaps", lambda s: _pct(s.support_rate("book")))
        for problem in PROBLEMS:
            row(f"Flagged: {problem}", lambda s, p=problem: str(s.problems(p)))
        row("Judge errors", lambda s: str(s.judge_errors))
        row("Unseen-name retries / left", lambda s: f"{s.name_retries} / {len(s.unseen_names)}")
        row("Cut-off replies / skipped rollups", lambda s: f"{s.truncated} / {s.rollups_skipped}")
        row("Tokens in + out", lambda s: f"{s.prompt_tokens:,} + {s.completion_tokens:,}")
        row("Cost (summaries)", lambda s: "n/a" if s.cost_usd is None else f"${s.cost_usd:.4f}")
        lines.append("")
        for s in rows:
            lines.append(f"### `{s.model}` on {target}")
            lines.append("")
            if s.leaked:
                lines.append(f"- Leaked: {', '.join(s.leaked)}")
            for case, misses in s.coverage_misses.items():
                lines.append(f"- Coverage miss {case}: {', '.join(misses)}")
            for where, names in s.unseen_names.items():
                lines.append(f"- Unseen names left in {where}: {', '.join(names)}")
            for f in sorted(s.flagged, key=lambda f: PROBLEMS.index(f["problem"])):
                quote = f"“{f['sentence']}”"
                lines.append(f"- **{f['problem']}** ({f['where']}): {quote} {f['reason']}")
            if not (s.leaked or s.coverage_misses or s.unseen_names or s.flagged):
                lines.append("- Nothing flagged.")
            lines.append("")
    return "\n".join(lines)
