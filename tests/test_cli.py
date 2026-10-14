import json

from epub_factory import omnibus
from typer.testing import CliRunner

from tome.cli import app

runner = CliRunner()


def test_eval_run_on_stub_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from conftest import REPO

    result = runner.invoke(
        app, ["eval", "run", "--stub", "--json", "--cases", str(REPO / "evals/public/monte-cristo")]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["leak_rate"] == 0.0 and report["coverage"] == 1.0
    assert 0 < report["quote_check_pass_rate"] < 1


def test_parse_build_search_ask(tmp_path):
    epub = omnibus(tmp_path / "o.epub")
    (tmp_path / "o.layout.toml").write_text('split = "toc"\n')
    out = runner.invoke(app, ["parse", str(epub)])
    assert out.exit_code == 0 and "2 book(s)" in out.output

    pack = tmp_path / "o.tome"
    out = runner.invoke(
        app, ["pack", "build-text", str(epub), "--out", str(pack), "--series", "omnibus"]
    )
    assert out.exit_code == 0, out.output
    info = runner.invoke(app, ["pack", "info", str(pack)])
    assert "pack_id              omnibus" in info.output

    early = runner.invoke(app, ["search", "gw0", "--pack", str(pack), "--at", "b2 ch1"])
    late = runner.invoke(app, ["search", "gw0", "--pack", str(pack), "--at", "b2 ch2"])
    assert "gw0" not in early.stdout and "gw0" in late.stdout


def test_init_private_copies_templates(tmp_path):
    dest = tmp_path / "library" / "evals"
    out = runner.invoke(app, ["eval", "init-private", "--dest", str(dest)])
    assert out.exit_code == 0
    names = sorted(p.name for p in dest.iterdir())
    assert "harry-potter.spoiler.jsonl" in names and "README.md" in names
    again = runner.invoke(app, ["eval", "init-private", "--dest", str(dest)])
    assert "exists, skipped" in again.output
