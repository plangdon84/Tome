#!/usr/bin/env python3
"""Do two independent drafts of a chapter summary agree on its errors?

Uses two `tome compare` runs of the same models (docs/results/model-comparison-
round-2.md). For each chapter, a checker model reads every sentence of run A's
summary next to run B's summary of the same chapter and says whether B states
the same thing (agree), says something incompatible (conflict) or doesn't say
it (absent); then the same from B to A. Crossed with the support judge's flags,
this shows what a "keep only what two drafts agree on" filter would do: how many
judged errors it removes, and how many unflagged sentences it throws away.

Usage:
  uv run python scripts/agreement.py data/compare/round2-run1 data/compare/round2-run2 \\
      --model meta-llama/llama-3.3-70b-instruct --model qwen/qwen3-14b

Verdicts are cached in <run A>/agreement/, so a rerun only pays for what is missing.
Public-domain packs only: the checker is a third-party API.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tome.compare import HOSTS, JUDGE_MODEL, TARGETS, _norm, judge_items, slug
from tome.llm.client import ChatClient, LLMError, pin_host
from tome.llm.providers import get_provider
from tome.series import Series
from tome.summarize import sentences

PROMPT_VERSION = "agreement-v1"
SYSTEM = """You compare two summaries of the same chapter of a book, written independently. \
For EACH numbered sentence of SUMMARY A, decide what SUMMARY B says about the same thing:
- agree: B states the same facts (wording, detail and order may differ).
- conflict: B states something incompatible (a different person, event, outcome, order or \
relation).
- absent: B doesn't mention it.
Judge only the summaries against each other, never against what you know of the book."""
SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["agree", "conflict", "absent"]},
                },
                "required": ["n", "verdict"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}
VERDICTS = ("agree", "conflict", "absent", "error")
FLAGS = ("contradicted", "unsupported", "speculation", "none")


def chapters(pack: Path) -> dict[str, str]:
    return {i.key: i.text for i in judge_items(pack) if i.kind == "chapter"}


def flags(run: Path, target: str, model: str) -> dict[str, dict[str, str]]:
    """{chapter key: {normalized sentence: problem}} from the support judge."""
    saved = json.loads((run / "judgments" / f"{target}--{slug(model)}.json").read_text())
    return {
        j["key"]: {_norm(f["sentence"]): f["problem"] for f in j["flags"]}
        for j in saved["judgments"]
        if j["kind"] == "chapter"
    }


def check(client: ChatClient, a: str, b: str) -> list[str]:
    """A verdict for each sentence of ``a``, against ``b``."""
    sents = sentences(a)
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sents, start=1))
    try:
        out = client.structured(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"SUMMARY A:\n{numbered}\n\nSUMMARY B:\n{b}"},
            ],
            SCHEMA, name="agreement", purpose="agreement", max_tokens=1500,
        )  # fmt: skip
    except LLMError:
        return ["error"] * len(sents)
    got = {v["n"]: v["verdict"] for v in out["verdicts"]}
    return [got.get(i, "error") for i in range(1, len(sents) + 1)]


def compare_pair(client, run_a: Path, run_b: Path, target: str, model: str, workers: int):
    """Rows of (flag, verdict) for every chapter sentence of both runs, checked both ways."""
    cache = run_a / "agreement" / f"{target}--{slug(model)}.json"
    done = json.loads(cache.read_text()) if cache.exists() else {}
    if done.get("prompt_version") != PROMPT_VERSION or done.get("checker") != client.model:
        done = {"prompt_version": PROMPT_VERSION, "checker": client.model, "verdicts": {}}
    packs = [r / f"{target}--{slug(model)}.tome" for r in (run_a, run_b)]
    texts = [chapters(p) for p in packs]
    judged = [flags(r, target, model) for r in (run_a, run_b)]
    jobs = []
    for d, (src, other) in enumerate([(0, 1), (1, 0)]):
        for key, text in texts[src].items():
            if key in texts[other] and f"{d}:{key}" not in done["verdicts"]:
                jobs.append((f"{d}:{key}", text, texts[other][key]))
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda j: check(client, j[1], j[2]), jobs))
    for job, verdicts in zip(jobs, results, strict=True):
        done["verdicts"][job[0]] = verdicts
    # Errors aren't cached as answers: a rerun asks again.
    keep = {k: v for k, v in done["verdicts"].items() if "error" not in v}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({**done, "verdicts": keep}, indent=1))
    rows = []
    for d, src in ((0, 0), (1, 1)):
        for key, text in texts[src].items():
            verdicts = done["verdicts"].get(f"{d}:{key}")
            if verdicts is None:
                continue
            problems = judged[src].get(key, {})
            for sentence, verdict in zip(sentences(text), verdicts, strict=True):
                rows.append((problems.get(_norm(sentence), "none"), verdict))
    return rows


def table(rows) -> list[str]:
    c = Counter(rows)
    lines = [
        "| Judge's flag | Sentences | Agree | Conflict | Absent | Dropped by the filter |",
        "|---|---|---|---|---|---|",
    ]
    for flag in FLAGS:
        n = sum(c[(flag, v)] for v in VERDICTS)
        if not n:
            continue
        dropped = n - c[(flag, "agree")]
        lines.append(
            f"| {flag} | {n} | {c[(flag, 'agree')]} | {c[(flag, 'conflict')]} | "
            f"{c[(flag, 'absent')]} | {dropped} ({100 * dropped / n:.0f}%) |"
        )
    errors = sum(c[(f, "error")] for f in FLAGS)
    if errors:
        lines.append(f"\n{errors} sentences had no verdict (checker errors).")
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("run_a", type=Path)
    p.add_argument("run_b", type=Path)
    p.add_argument("--model", action="append", required=True)
    p.add_argument("--target", action="append", default=None)
    p.add_argument("--checker", default=JUDGE_MODEL)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    provider = get_provider("openrouter")
    out = [f"Checker: `{args.checker}` (prompt `{PROMPT_VERSION}`). A sentence is *dropped* "
           "unless the other run's summary of the chapter agrees with it.", ""]  # fmt: skip
    for model in args.model:
        everything = []
        for target in args.target or list(TARGETS):
            series = Series.find(TARGETS[target].series)
            route = pin_host(HOSTS[args.checker]) if args.checker in HOSTS else None
            client = ChatClient(provider, series, model=args.checker, timeout=600, route=route)
            try:
                rows = compare_pair(client, args.run_a, args.run_b, target, model, args.workers)
            finally:
                client.close()
            print(f"{target} {model}: {len(rows)} sentences", file=sys.stderr)
            out += [f"### `{model}` on {target}", "", *table(rows), ""]
            everything += rows
        out += [f"### `{model}`, both targets", "", *table(everything), ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
