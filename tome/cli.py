"""The ``tome`` command line."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import typer

from tome.horizon import Anchor, HorizonReader, resolve_anchor

app = typer.Typer(no_args_is_help=True, help="Tome: a spoiler-safe reading companion.")
corpus_app = typer.Typer(no_args_is_help=True, help="Public-domain development corpus.")
pack_app = typer.Typer(no_args_is_help=True, help="Build and inspect series packs.")
eval_app = typer.Typer(no_args_is_help=True, help="Spoiler and coverage evals.")
llm_app = typer.Typer(no_args_is_help=True, help="LLM provider utilities.")
app.add_typer(corpus_app, name="corpus")
app.add_typer(pack_app, name="pack")
app.add_typer(eval_app, name="eval")
app.add_typer(llm_app, name="llm")


# ------------------------------------------------------------------ corpus --


@corpus_app.command("fetch")
def corpus_fetch(
    keys: list[str] = typer.Argument(None, help="Catalog keys (default: all)."),
    dest: Path = typer.Option(Path("corpus"), help="Download directory."),
    force: bool = typer.Option(False, help="Re-download even if present."),
):
    """Download public-domain EPUBs into corpus/ (gitignored)."""
    from tome.corpus import CATALOG, expand, fetch

    for key in expand(keys or list(CATALOG)):
        if key not in CATALOG:
            raise typer.BadParameter(f"unknown key {key!r}; known: {sorted(CATALOG)}")
        typer.echo(f"{key}: {fetch(key, dest, force=force)}")


@corpus_app.command("list")
def corpus_list():
    """List the public-domain catalog."""
    from tome.corpus import CATALOG, SERIES

    for book in CATALOG.values():
        typer.echo(f"{book.key:28} {book.title}")
    for name, keys in SERIES.items():
        typer.echo(f"{name:28} series: {' '.join(keys)}")


# ------------------------------------------------------------------- parse --


@app.command()
def parse(
    epub: Path,
    layout: Path | None = typer.Option(None, help="Layout TOML."),
    chapters: bool = typer.Option(False, "--chapters", help="List every chapter."),
):
    """Parse an EPUB and report books, chapters and passage sizes (nothing is stored)."""
    from tome.epub.parse import Layout, parse_epub
    from tome.text import word_count

    result = parse_epub(epub, Layout.for_epub(epub, layout))
    typer.echo(f"{result.title}: {len(result.books)} book(s)")
    for i, book in enumerate(result.books, start=1):
        sizes = [word_count(p) for c in book.chapters for p in c.passages]
        typer.echo(
            f"  b{i} {book.title!r}: {len(book.chapters)} chapters, {len(sizes)} "
            f"passages, {sum(sizes):,} words (passage words min {min(sizes)}, "
            f"median {sorted(sizes)[len(sizes) // 2]}, max {max(sizes)})"
        )
        if chapters:
            for n, ch in enumerate(book.chapters, start=1):
                typer.echo(f"     ch{n:<4} {ch.title}  ({len(ch.passages)} passages)")
    for w in result.warnings:
        typer.echo(f"  warning: {w}")
    if result.hint:
        typer.echo(f"  hint: {result.hint}")


# -------------------------------------------------------------------- pack --


@pack_app.command("build-text")
def pack_build_text(
    epubs: list[Path] = typer.Argument(..., help="EPUB files in reading order."),
    out: Path = typer.Option(..., help="Pack file to write (e.g. corpus/monte-cristo.tome)."),
    series: str = typer.Option(..., help="Series id (pack_id)."),
    title: str | None = typer.Option(None, help="Series title (default: first EPUB title)."),
    layout: Path | None = typer.Option(None, help="Layout TOML (applies to every EPUB)."),
    embed: bool = typer.Option(False, help="Embed passages with the pinned model."),
    force: bool = typer.Option(False, help="Overwrite an existing pack."),
):
    """Build a parse-only pack (books, chapters, passages, FTS; no LLM)."""
    from tome.epub.parse import Layout, parse_epub
    from tome.pack_writer import PackWriter

    results = [(e, parse_epub(e, Layout.for_epub(e, layout))) for e in epubs]
    w = PackWriter(out, pack_id=series, series_title=title or results[0][1].title, overwrite=force)
    run = w.start_run("parse", params={"epubs": [e.name for e in epubs]})
    number = 0
    for epub, result in results:
        for book in result.book_texts(source_file=epub.name):
            number += 1
            w.add_book(number, book)
    embedding_model_id = None
    if embed:
        from tome.embed import OnnxEmbedder, to_blob

        embedder = OnnxEmbedder()
        rows = w.conn.execute("SELECT passage_id, pos, text FROM passages ORDER BY pos").fetchall()
        started = time.monotonic()
        vecs = embedder.embed_passages([r["text"] for r in rows])
        erun = w.start_run("embed", params={"model": embedder.model_id})
        w.add_embeddings(
            (
                (("passages", r["passage_id"], to_blob(v), r["pos"]))
                for r, v in zip(rows, vecs, strict=True)
            ),
            model_id=embedder.model_id,
            dim=embedder.dim,
            run_id=erun,
        )
        w.finish_run(
            erun, stats={"passages": len(rows), "seconds": round(time.monotonic() - started, 1)}
        )
        embedding_model_id = embedder.model_id
    w.finish_run(run, stats={"books": number})
    content_hash = w.finalize(embedding_model_id=embedding_model_id)
    w.close()
    typer.echo(f"wrote {out} ({number} book(s), content hash {content_hash[:12]})")


@pack_app.command("info")
def pack_info(pack: Path):
    """Show a pack's manifest and table sizes."""
    with HorizonReader(pack, 0) as r:
        for k, v in r.manifest().items():
            typer.echo(f"{k:20} {v}")
        for b in r.books():
            typer.echo(f"book {b['number']}: {b['title']} (pos {b['start_pos']}-{b['end_pos']})")
        for run in r.query("SELECT run_id, kind, llm_model, stats_json FROM runs"):
            typer.echo(
                f"run {run['run_id']}: {run['kind']} {run['llm_model'] or ''} {run['stats_json']}"
            )


# ------------------------------------------------------------ reading time --


def _reader(pack: Path, at: str) -> HorizonReader:
    res = resolve_anchor(pack, Anchor.parse(at))
    typer.echo(f"[horizon {at} -> pos {res.pos}{'' if res.exact else ' (rounded back)'}]", err=True)
    return HorizonReader(pack, res.pos)


@app.command()
def search(
    query: str,
    pack: Path = typer.Option(...),
    at: str = typer.Option(..., help='Horizon, e.g. "b1 ch30" (finished chapter 30).'),
    limit: int = typer.Option(5),
):
    """Keyword search over passages you have already read."""
    with _reader(pack, at) as r:
        for p in r.search_passages(query, limit=limit):
            typer.echo(f"pos {p['pos']}: {p['text'][:300]}...\n")


@app.command()
def ask(question: str, pack: Path = typer.Option(...), at: str = typer.Option(...)):
    """Answer from the pack alone with the Phase 0 baseline answerer (no LLM)."""
    from tome.answer import answer

    with _reader(pack, at) as r:
        ans = answer(r, question)
    if not ans.pieces:
        typer.echo("Nothing found up to this point.")
    for piece in ans.pieces:
        typer.echo(f"- [{piece.kind}] {piece.text}")


# -------------------------------------------------------------------- eval --


@eval_app.command("stub")
def eval_stub(out: Path = typer.Option(Path("data/monte-cristo-stub.tome"))):
    """Write the hand-written stub pack."""
    from tome.evals.stub import build_stub_pack

    out.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"wrote {build_stub_pack(out)}")


@eval_app.command("run")
def eval_run(
    cases: list[Path] = typer.Option(
        [Path("evals/public/monte-cristo")], help="Case files or directories."
    ),
    pack: Path | None = typer.Option(None, help="Pack to evaluate."),
    stub: bool = typer.Option(False, "--stub", help="Evaluate the built-in stub pack."),
    as_json: bool = typer.Option(False, "--json", help="Print the full report as JSON."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
    fail_on_leak: bool = typer.Option(True, help="Exit 1 if any spoiler case leaks."),
):
    """Run spoiler and coverage cases; report leak rate, coverage and quote-check pass rate."""
    from tome.evals.runner import format_report, load_cases, run_eval

    if stub == (pack is not None):
        raise typer.BadParameter("give exactly one of --pack or --stub")
    if stub:
        from tome.evals.stub import build_stub_pack

        pack = build_stub_pack(Path("data") / "monte-cristo-stub.tome")
    loaded = [c for path in cases for c in load_cases(path)]
    report = run_eval(pack, loaded)
    typer.echo(
        json.dumps(report.to_json(), indent=2, ensure_ascii=False)
        if as_json
        else format_report(report, verbose=verbose)
    )
    if fail_on_leak and report.leak_rate:
        raise typer.Exit(1)


@eval_app.command("init-private")
def eval_init_private(dest: Path = typer.Option(Path("library/evals"))):
    """Copy the private eval templates into library/evals/ (gitignored)."""
    src = Path(__file__).resolve().parent.parent / "evals" / "templates" / "private"
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):
        target = dest / f.name.replace(".template", "")
        if target.exists():
            typer.echo(f"exists, skipped: {target}")
            continue
        shutil.copy(f, target)
        typer.echo(f"created {target}")


# --------------------------------------------------------------------- llm --


@llm_app.command("smoke")
def llm_smoke(
    series: str = typer.Option("monte-cristo"),
    provider: str = typer.Option("openrouter"),
    model: str | None = typer.Option(None),
):
    """One tiny structured call, to check a provider end to end."""
    from tome.llm.client import ChatClient
    from tome.llm.providers import get_provider
    from tome.series import Series

    client = ChatClient(get_provider(provider), Series.find(series), model=model)
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    out = client.structured(
        [
            {
                "role": "user",
                "content": "Text: 'Ah, is it you, Dantès?' cried the man in the "
                "skiff. Who is being addressed? Give just the name.",
            }
        ],
        schema,
        name="person",
        purpose="smoke",
        max_tokens=50,
    )
    rec = client.usage.records[-1]
    typer.echo(
        f"{out} model={rec.model} tokens={rec.prompt_tokens}+{rec.completion_tokens} "
        f"cost={rec.cost_usd}"
    )


if __name__ == "__main__":
    app()
