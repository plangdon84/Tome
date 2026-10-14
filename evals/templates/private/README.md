# Private eval sets (templates)

Eval cases for copyrighted series live in **`library/evals/`**, which is
gitignored and never leaves your machine. This directory holds the committed
templates. Copy them into place with:

```sh
uv run tome eval init-private          # copies to library/evals/ (won't overwrite)
```

Then edit the copies and run them against a pack you compiled on the GPU pod:

```sh
uv run tome eval run --pack library/packs/harry-potter.tome --cases library/evals/
```

## Format

JSON Lines, one case per line. Lines starting with `//` are comments.

```json
{"id": "hp-s01", "series": "harry-potter", "horizon": "b3 ch10",
 "question": "Who is Scabbers?", "must_not_include": ["Pettigrew", "Wormtail", "Animagus"],
 "subject_terms": ["Scabbers"], "notes": "Revealed in the Shrieking Shack, b3 ch17-19."}

{"id": "cr-c01", "series": "cradle", "horizon": "b2 ch5",
 "question": "What comes after Copper?", "expected_facts": ["Iron"]}
```

- `series` must equal the pack's `pack_id` (cases for other series are skipped).
- `horizon` is `"bN chM"` = *finished* chapter M of book N. Chapter numbers are
  the 1-based order of chapters in the parsed book (check with `tome parse`),
  which for most books is the printed number.
- `must_not_include`: phrases that would reveal something after the horizon.
  Matching is case- and accent-insensitive on whole words. Prefer phrases that
  cannot legitimately appear before the horizon (e.g. "Pettigrew" at book 3
  ch 10), or set `subject_terms` and pick phrases that never appear *next to the
  subject* before the horizon.
- `expected_facts`: facts a good answer must contain. Use `"a|b"` for
  alternative wordings.
- Optional: `notes`, `subject_terms`.

Never paste passages of book text into these files. Questions, short names and
short phrases only.

## What goes in each file

| File | Purpose | Size |
|---|---|---|
| `harry-potter.spoiler.jsonl` | Worst-case leaks: every LLM knows the plot. | ~30 |
| `cradle.coverage.jsonl` | Usefulness and power-system questions. | ~30 |
| `reading-notes.coverage.jsonl` | Real questions you write down while reading, with the horizon you were at. **The viability test.** | grows |

Each "spoiled me" report from real use becomes a new spoiler case.
