# Tome

> Never lose the plot.

A private, spoiler-safe reading companion for long fantasy and speculative-fiction series. You import the EPUBs you own and tell Tome where you are in the series. It answers "who is this?", "what happened last book?", and similar questions using **only what you've read so far**, and cites the passages its answers come from.

Status: Phase 0 (foundations and eval harness) complete; see [`docs/PLAN.md`](docs/PLAN.md).

## Docs

- [`docs/original-direction.md`](docs/original-direction.md): the initial product direction.
- [`docs/REVIEW.md`](docs/REVIEW.md): a critical review covering spoiler-model gaps, competitors, compute, reading position, and legal/ethics.
- [`docs/PLAN.md`](docs/PLAN.md): the phased build plan with decision gates.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the LLM compiles the books at ingestion, and questions are answered on-device from the database.
- [`docs/DECISIONS.md`](docs/DECISIONS.md): setup-specific decisions covering hardware, model and cost, test series, and position capture.
- [`docs/AUTHOR_OUTREACH.md`](docs/AUTHOR_OUTREACH.md): a guide for conversations with indie authors.
- [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md): step-by-step setup of the `tome` CLI on the Intel MacBook Air, and checking how the omnibus EPUB splits.

## Ground rules

- DRM-free books only. No DRM removal.
- Copyrighted book text never goes in this repo (`library/` is gitignored). Tests use public-domain works.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+ (on an Intel Mac, exactly
3.12 or 3.13: see [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md)).

```sh
uv sync                                  # create .venv with all dependencies
uv run pytest                            # offline test suite
uv run ruff check . && uv run ruff format --check .
```

Opt-in tests: `--run-corpus` (needs the public-domain EPUBs below),
`--run-model` (downloads the ~34 MB embedding model from Hugging Face) and
`--run-live` (one real LLM call costing a fraction of a cent).

```sh
uv run tome corpus fetch                 # public-domain EPUBs -> corpus/ (gitignored)
uv run tome parse corpus/monte-cristo.epub
uv run tome pack build-text corpus/monte-cristo.epub --series monte-cristo \
    --out data/monte-cristo.tome --embed
uv run tome search "Sinbad" --pack data/monte-cristo.tome --at "b1 ch31"
uv run tome eval run --stub              # evals end to end on the stub pack
uv run tome eval run --pack data/monte-cristo.tome
uv run tome eval init-private            # private eval templates -> library/evals/
uv run tome llm smoke                    # one cheap call via OpenRouter
```

Layout:

| Path | What |
|---|---|
| `tome/migrations/` | Plain-SQL schema for the series pack and `user.sqlite` |
| `tome/horizon.py` | The horizon-safe data-access layer: the only reader of a pack |
| `tome/pack_writer.py` | Write side, used by the compiler at ingestion |
| `tome/epub/` | EPUB reader, chapter detection, omnibus layout files, passages |
| `tome/llm/` | OpenAI-compatible client, provider presets, per-series provider policy |
| `tome/embed.py` | The pinned embedding model (bge-small-en-v1.5, ONNX) |
| `tome/evals/`, `evals/` | Eval runner, stub pack, public Monte Cristo cases, private templates |
| `series/` | Per-series config: rights and allowed LLM providers |

LLM credentials: OpenRouter uses `OPENROUTER_API_KEY` when set. In Claude Code
cloud sessions the network proxy injects the key, so the code sends a
placeholder. Copyrighted series (anything not marked `public_domain`) can only
be sent to self-hosted providers on a local or private address. This is
enforced in `tome/llm/policy.py`.
