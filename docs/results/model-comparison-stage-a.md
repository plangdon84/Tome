# Model comparison, Stage A: results (2026-11-07)

Stage A of the comparison in [DECISIONS.md §12](../DECISIONS.md): public-domain
books, automated scores, through OpenRouter. The full machine-generated report,
including every flagged sentence and the judge's reason for flagging it, is in
[model-comparison-stage-a-full.md](model-comparison-stage-a-full.md).

Reproduce with `uv run tome corpus fetch oz monte-cristo` and
`uv run tome compare --target oz --target monte-cristo`. It takes about 25 minutes.

## Setup

- **Small:** `qwen/qwen-2.5-7b-instruct`, the model the pod runs now.
- **Large:** `qwen/qwen-2.5-72b-instruct`, the ~70B tier (AWQ on `g6e.xlarge`).
- **Judge:** `deepseek/deepseek-v3.2`. It is open-weight, much larger than
  both models, and from a different family. It reads each summary next to the
  inputs it was written from, and flags sentences as *contradicted* (the
  inputs say otherwise), *unsupported* (the inputs don't say it) or
  *speculation* (a guess or hint).
- **Text:** Oz books 1–2, 48 chapters with the Tip = Ozma reveal in book 2.
  *Monte Cristo* ch 1–34, so the persona chapters (23–34) have their real
  rolling context.
- **Prompts:** `summaries-v4` for the summaries, `support-v1` for the judge.

## Results

| | Oz 7B | Oz 72B | MC 7B | MC 72B |
|---|---|---|---|---|
| Spoiler leaks | 0/6 | 0/6 | 1/11* | 1/11* |
| Coverage, cases fully met | 4/6 | 2/6 | 6/11† | 6/11† |
| **Contradicted sentences** | **34** | **15** | **36** | **7** |
| Unsupported | 160 | 176 | 158 | 138 |
| Speculation | 2 | 6 | 15 | 11 |
| Support, chapter summaries | 65.8% | 78.6% | 57.1% | 68.9% |
| Support, story so far | 72.5% | 69.8% | 78.8% | 84.9% |
| Summary cost | $0.024 | $0.103 | $0.031 | $0.137 |

The judge cost about $0.33 across all four packs, so the whole run cost about
$0.62.

\* Both models fail `mc-s11` (Sinbad is not stated to be Dantès). The leak is
not in the summaries: the baseline answerer's keyword fallback shows raw
passages about Dantès as a sailor, and a parse-only pack with no summaries
fails it the same way. Fix this in the Phase 3 query pipeline, or narrow the
fallback.

† `mc-c09` and `mc-c11` have horizons past ch 34, so they can't pass on this
pack. In range, both models met 6/9 cases and missed the same three:
`mc-c01` (Bonapartist letter), `mc-c02` (betrothed) and `mc-c05` (Sinbad
the Sailor).

## What it shows

1. **The 72B model makes 2–5× fewer factual errors.** Its contradicted
   sentences numbered 15 against 34 on Oz, and 7 against 36 on *Monte Cristo*.
   This is the clearest signal in the run.
2. **The 7B model's errors carry forward.** It invented "Mombi transforms
   Tip into a marble statue" (she only plans to), and the claim then appears in
   four story-so-far rollups in a row (book 2 ch 10, 15, 20 and 24). Rolling
   summaries copy a wrong fact once it is in.
3. **Neither model leaked a spoiler through its summaries.** Spoilers don't
   separate the two models at this size, which matches the trial run on the pod.
4. **Coverage is noisy, and it favours neither model.** The 72B pack missed
   "Cowardly Lion" in the ch 12 rollup and "humbug" in the end-of-book rollup,
   both of which the 7B pack had. Coverage depends on single words surviving
   the rollups, so it moves with small changes (see PLAN.md Phase 1 notes).
   Both models missed `oz-c01` (Ozma, b2 ch23) and `oz-c02` (humbug, b1 ch15).
5. **"Unsupported" doesn't tell the models apart.** The judge is strict: most
   of these flags are small embellishments ("lifeless prairie") or compressed
   order of events, and the two models have similar counts. Some contradicted
   flags are judge mistakes too (for example, "Toto remains calm"). Use the
   counts to compare models, not as absolute error rates.

## For Stage B

Stage A points to the 72B model, mainly because it makes far fewer factual
errors. DECISIONS.md's rule still decides on Stage B (keep the smaller model
unless it has any spoiler, or at least 2 more factual errors), and on these
numbers the 7B model is likely to fail the factual-error half of that rule.
The 72B model costs about 4× more per token on OpenRouter. On the pod both
fit on one `g6e.xlarge`, so the real cost difference there is runtime.

Things to watch in Stage B:

- whether a 7B error made early in a window repeats in later rollups;
- whether 72B's lower coverage shows up as missing key facts in recaps.

Two follow-ups for the summary pipeline, whichever model is kept:

- the "story so far" rollup should be checked against the chapter summaries it
  is built from, so an invented fact isn't carried forward;
- the coverage drop in rollups.
