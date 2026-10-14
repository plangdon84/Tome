from pathlib import Path

import pytest

from tome.pack_writer import BookText, ChapterText, PackWriter

REPO = Path(__file__).resolve().parent.parent
OPT_MARKERS = {"live": "--run-live", "model": "--run-model", "corpus": "--run-corpus"}


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="run tests that call a paid LLM API")
    parser.addoption(
        "--run-model",
        action="store_true",
        help="run tests that download/run the real embedding model",
    )
    parser.addoption(
        "--run-corpus", action="store_true", help="run tests that need corpus/monte-cristo.epub"
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker, opt in OPT_MARKERS.items():
            if marker in item.keywords and not config.getoption(opt):
                item.add_marker(pytest.mark.skip(reason=f"needs {opt}"))


@pytest.fixture(scope="session")
def stub_pack(tmp_path_factory) -> Path:
    from tome.evals.stub import build_stub_pack

    return build_stub_pack(tmp_path_factory.mktemp("packs") / "monte-cristo-stub.tome")


def words(n: int, tag: str) -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


@pytest.fixture
def tiny_pack(tmp_path) -> Path:
    """Two books, 2 chapters each, 2 passages per chapter: pos 1..8.

    One derived row of each kind sits at pos 2 (early) and pos 7 (late).
    """
    path = tmp_path / "tiny.tome"
    w = PackWriter(path, pack_id="tiny", series_title="Tiny")
    for b in (1, 2):
        chapters = [
            ChapterText(
                f"B{b} Chapter {c}",
                [
                    f"Book {b} chapter {c} passage {p} "
                    + words(20, "w")
                    + (" the secret is out" if (b, c, p) == (2, 2, 1) else "")
                    for p in (1, 2)
                ],
            )
            for c in (1, 2)
        ]
        w.add_book(b, BookText(f"Book {b}", chapters))
    run = w.start_run("test")
    early = w.add_entity(kind="person", first_pos=2, run_id=run)
    late = w.add_entity(kind="person", first_pos=7, run_id=run)
    w.add_alias(entity_id=early, surface_form="The Stranger", established_at=2, run_id=run)
    w.add_alias(entity_id=late, surface_form="Secret Name", established_at=7, run_id=run)
    w.add_alias(entity_id=early, surface_form="Secret Name", established_at=7, run_id=run)
    w.add_identity(entity_id=early, same_as_entity_id=late, established_at=7, run_id=run)
    for pos, tag in ((2, "early"), (7, "late")):
        pid = w.passage_at(pos)["passage_id"]
        w.add_observation(
            sentence=f"{tag} observation",
            subject_entity_id=early,
            predicate="p",
            evidence_passage_id=pid,
            quote=w.passage_at(pos)["text"][:40],
            run_id=run,
        )
        w.add_relationship(
            source_entity_id=early,
            target_entity_id=late,
            rel_type="t",
            description=f"{tag} relationship",
            pos=pos,
            run_id=run,
        )
        w.add_profile(
            entity_id=early,
            checkpoint_pos=pos,
            display_name="X",
            profile_text=f"{tag} profile",
            max_source_pos=pos,
            run_id=run,
        )
        chapter_id = w.conn.execute(
            "SELECT chapter_id FROM passages WHERE pos=?", (pos,)
        ).fetchone()[0]
        w.add_chapter_summary(
            chapter_id=chapter_id, summary_text=f"{tag} summary", max_source_pos=pos, run_id=run
        )
        w.add_rollup(kind="story_so_far", text=f"{tag} rollup", max_source_pos=pos, run_id=run)
        w.add_anticipated_qa(
            chapter_id=chapter_id,
            question=f"{tag} question?",
            answer=f"{tag} answer",
            evidence_passage_ids=[pid],
            max_source_pos=pos,
            run_id=run,
        )
        w.add_embeddings([("passages", pid, b"\x00" * 16, pos)], model_id="m", dim=4, run_id=run)
    w.finish_run(run)
    w.finalize()
    w.close()
    return path
