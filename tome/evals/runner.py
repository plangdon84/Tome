"""Eval harness: spoiler cases, coverage cases, and the quote check.

Case files are JSON Lines. One case per line:

    spoiler:  {"id", "series", "horizon", "question", "must_not_include": [...]}
    coverage: {"id", "series", "horizon", "question", "expected_facts": [...]}

``horizon`` is ``"b1 ch24"`` (finished chapter 24 of book 1) or an object
``{"book": 1, "chapter": 24, "fingerprint": "..."}``. Phrases match
case-insensitively, accent-insensitively, on word boundaries. An expected
fact may list alternatives with ``|`` ("Dantès|Edmond"). Optional fields:
``notes``, ``reveal`` (where the spoiler is revealed), ``tags``.

Files whose name contains ``spoiler`` or ``coverage`` are loaded by kind;
otherwise the kind is inferred from the fields present.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tome.answer import Answer, answer
from tome.horizon import Anchor, HorizonReader, resolve_anchor
from tome.quote import quote_verifies
from tome.text import fold


class CaseError(ValueError):
    pass


@dataclass
class Case:
    id: str
    kind: str  # 'spoiler' | 'coverage'
    series: str
    anchor: Anchor
    question: str
    phrases: list[str]  # must_not_include or expected_facts
    notes: str = ""
    source: str = ""
    # Spoiler cases: terms naming the question's subject. Used to validate a case
    # against the real text (a must-not phrase may legitimately appear before the
    # horizon, just never alongside the subject).
    subject_terms: list[str] = field(default_factory=list)


def _parse_anchor(value) -> Anchor:
    if isinstance(value, str):
        return Anchor.parse(value)
    if isinstance(value, dict) and {"book", "chapter"} <= value.keys():
        return Anchor(int(value["book"]), int(value["chapter"]), value.get("fingerprint"))
    raise CaseError(f"bad horizon {value!r}")


def load_cases(path: str | Path) -> list[Case]:
    path = Path(path)
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    cases, ids = [], set()
    for f in files:
        if f.name.startswith("_") or ".template." in f.name:
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip() or line.lstrip().startswith("//"):
                continue
            where = f"{f}:{lineno}"
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CaseError(f"{where}: {exc}") from exc
            if "must_not_include" in raw:
                kind, phrases = "spoiler", raw["must_not_include"]
            elif "expected_facts" in raw:
                kind, phrases = "coverage", raw["expected_facts"]
            else:
                raise CaseError(f"{where}: needs must_not_include or expected_facts")
            missing = {"id", "series", "horizon", "question"} - raw.keys()
            if missing:
                raise CaseError(f"{where}: missing {sorted(missing)}")
            if not phrases or not all(isinstance(p, str) and p.strip() for p in phrases):
                raise CaseError(f"{where}: phrases must be non-empty strings")
            if raw["id"] in ids:
                raise CaseError(f"{where}: duplicate id {raw['id']!r}")
            ids.add(raw["id"])
            cases.append(
                Case(
                    raw["id"],
                    kind,
                    raw["series"],
                    _parse_anchor(raw["horizon"]),
                    raw["question"],
                    list(phrases),
                    raw.get("notes", ""),
                    where,
                    list(raw.get("subject_terms", [])),
                )
            )
    return cases


def contains_phrase(text: str, phrase: str) -> bool:
    """Case/accent-insensitive whole-word match of any ``|`` alternative."""
    hay = fold(text)
    for alt in phrase.split("|"):
        needle = fold(alt).strip()
        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay):
            return True
    return False


@dataclass
class CaseResult:
    id: str
    kind: str
    question: str
    anchor: str
    horizon: int
    horizon_exact: bool
    passed: bool
    score: float  # 1/0 for spoiler, fraction found for coverage
    hits: list[str] = field(default_factory=list)  # leaked / found phrases
    misses: list[str] = field(default_factory=list)  # coverage facts not found
    hard_violation: bool = False  # a piece used text past the horizon
    shown: str = ""


@dataclass
class QuoteReport:
    candidates: int
    dropped: int
    stored: int
    stored_verified: int

    @property
    def pass_rate(self) -> float | None:
        if self.candidates:
            return (self.candidates - self.dropped) / self.candidates
        return self.stored_verified / self.stored if self.stored else None


@dataclass
class EvalReport:
    pack_id: str
    spoiler: list[CaseResult]
    coverage: list[CaseResult]
    quotes: QuoteReport
    skipped: list[str]

    @property
    def leak_rate(self) -> float | None:
        return sum(not r.passed for r in self.spoiler) / len(self.spoiler) if self.spoiler else None

    @property
    def coverage_score(self) -> float | None:
        return sum(r.score for r in self.coverage) / len(self.coverage) if self.coverage else None

    def to_json(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "leak_rate": self.leak_rate,
            "coverage": self.coverage_score,
            "quote_check_pass_rate": self.quotes.pass_rate,
            "quotes": asdict(self.quotes),
            "spoiler": [asdict(r) for r in self.spoiler],
            "coverage_cases": [asdict(r) for r in self.coverage],
            "skipped": self.skipped,
        }


Answerer = Callable[[HorizonReader, str], Answer]


def quote_report(pack: str | Path) -> QuoteReport:
    """Compiler drop stats from ``runs`` plus a re-check of every stored quote
    (observations and identity reveals)."""
    with HorizonReader(pack, _max_pos(pack)) as r:
        cands = dropped = 0
        for run in r.query("SELECT stats_json FROM runs"):
            stats = json.loads(run["stats_json"] or "{}")
            cands += stats.get("quote_candidates", 0)
            dropped += stats.get("quote_dropped", 0)
        rows = r.query(
            "SELECT o.quote_span, o.quote_start, o.quote_end, o.pos AS opos, p.pos AS ppos,"
            " p.text FROM h_observations o JOIN h_passages p"
            " ON p.passage_id = o.evidence_passage_id"
        )
        rows += r.query(
            "SELECT i.quote_span, i.quote_start, i.quote_end, i.established_at AS opos,"
            " p.pos AS ppos, p.text FROM h_entity_identities i JOIN h_passages p"
            " ON p.passage_id = i.evidence_passage_id"
        )
        ok = sum(
            1
            for x in rows
            if x["opos"] == x["ppos"]
            and quote_verifies(x["text"], x["quote_span"], x["quote_start"], x["quote_end"])
        )
    return QuoteReport(cands, dropped, len(rows), ok)


def _max_pos(pack: str | Path) -> int:
    with HorizonReader(pack, 0) as r:
        row = r.one("SELECT max(end_pos) AS m FROM books")
    return row["m"] or 0


def run_eval(
    pack: str | Path, cases: list[Case], *, answerer: Answerer = answer, series: str | None = None
) -> EvalReport:
    with HorizonReader(pack, 0) as r:
        pack_id = r.manifest().get("pack_id", "")
    series = series or pack_id
    results: dict[str, list[CaseResult]] = {"spoiler": [], "coverage": []}
    skipped = []
    for case in cases:
        if case.series != series:
            skipped.append(case.id)
            continue
        res = resolve_anchor(pack, case.anchor)
        with HorizonReader(pack, res.pos) as reader:
            ans = answerer(reader, case.question)
        shown = ans.text
        hard = ans.max_pos() > res.pos
        if case.kind == "spoiler":
            hits = [p for p in case.phrases if contains_phrase(shown, p)]
            passed = not hits and not hard
            result = CaseResult(
                case.id,
                case.kind,
                case.question,
                str(case.anchor),
                res.pos,
                res.exact,
                passed,
                1.0 if passed else 0.0,
                hits,
                [],
                hard,
                shown,
            )
        else:
            hits = [p for p in case.phrases if contains_phrase(shown, p)]
            misses = [p for p in case.phrases if p not in hits]
            score = len(hits) / len(case.phrases)
            result = CaseResult(
                case.id,
                case.kind,
                case.question,
                str(case.anchor),
                res.pos,
                res.exact,
                score == 1.0 and not hard,
                score,
                hits,
                misses,
                hard,
                shown,
            )
        results[case.kind].append(result)
    return EvalReport(pack_id, results["spoiler"], results["coverage"], quote_report(pack), skipped)


@dataclass
class CheckReport:
    pack_id: str
    checked: int
    skipped: list[str]
    problems: list[str]  # "<source>: <id>: <message>"


def check_cases(pack: str | Path, cases: list[Case], *, series: str | None = None) -> CheckReport:
    """Check cases against the pack's own text, before trusting their scores.

    - A spoiler phrase must not appear at or before the horizon. With
      ``subject_terms``, only passages mentioning the subject count.
    - At least one spoiler phrase must appear after the horizon (a real later fact).
    - Every coverage fact must appear at or before the horizon, word for word.
    - The horizon must name a chapter that exists (no rounding back).
    """
    with HorizonReader(pack, 0) as r:
        pack_id = r.manifest().get("pack_id", "")
    series = series or pack_id
    # Validation reads the whole book on purpose: it needs the text past each horizon.
    with HorizonReader(pack, _max_pos(pack)) as r:
        passages = [(p["pos"], p["text"]) for p in r.query("SELECT pos, text FROM h_passages")]
    checked, skipped, problems = 0, [], []
    for case in cases:
        if case.series != series:
            skipped.append(case.id)
            continue
        checked += 1

        def problem(msg: str, case=case):
            problems.append(f"{case.source}: {case.id}: {msg}")

        res = resolve_anchor(pack, case.anchor)
        if not res.exact:
            problem(f"horizon {case.anchor} does not exist; rounded back to pos {res.pos}")
        before = [t for pos, t in passages if pos <= res.pos]
        if case.kind == "spoiler":
            if case.subject_terms:
                before = [
                    t for t in before if any(contains_phrase(t, s) for s in case.subject_terms)
                ]
            for phrase in case.phrases:
                early = next((t for t in before if contains_phrase(t, phrase)), None)
                if early is not None:
                    problem(f"{phrase!r} already appears by the horizon: {early[:100]!r}")
            after = [t for pos, t in passages if pos > res.pos]
            if not any(contains_phrase(t, p) for p in case.phrases for t in after):
                problem("no phrase appears after the horizon, so the case cannot catch a leak")
        else:
            for fact in case.phrases:
                if not any(contains_phrase(t, fact) for t in before):
                    problem(f"{fact!r} does not appear in the text by the horizon")
    return CheckReport(pack_id, checked, skipped, problems)


def format_report(report: EvalReport, *, verbose: bool = False) -> str:
    def pct(x):
        return "n/a" if x is None else f"{100 * x:.1f}%"

    lines = [f"Eval report for pack '{report.pack_id}'", ""]
    n_leaks = sum(not r.passed for r in report.spoiler)
    lines.append(
        f"  Leak rate:        {pct(report.leak_rate)}  "
        f"({n_leaks}/{len(report.spoiler)} spoiler cases leaked)"
    )
    full = sum(r.passed for r in report.coverage)
    lines.append(
        f"  Coverage:         {pct(report.coverage_score)}  "
        f"({full}/{len(report.coverage)} cases fully covered)"
    )
    q = report.quotes
    lines.append(
        f"  Quote-check pass: {pct(q.pass_rate)}  ({q.candidates - q.dropped}/"
        f"{q.candidates} candidates kept; {q.stored_verified}/{q.stored} stored "
        "quotes re-verified)"
    )
    if report.skipped:
        lines.append(f"  Skipped (other series): {len(report.skipped)}")
    for r in report.spoiler:
        if not r.passed or verbose:
            status = "PASS" if r.passed else "LEAK"
            extra = f" leaked={r.hits}" if r.hits else ""
            extra += " HARD-VIOLATION" if r.hard_violation else ""
            lines.append(f"  [{status}] {r.id} @ {r.anchor}: {r.question}{extra}")
    for r in report.coverage:
        if not r.passed or verbose:
            status = "FULL" if r.passed else f"{100 * r.score:.0f}%"
            extra = f" missing={r.misses}" if r.misses else ""
            lines.append(f"  [{status}] {r.id} @ {r.anchor}: {r.question}{extra}")
    return "\n".join(lines)
