# Model comparison, round 2: nine candidates (2026-11-08)

Round 1 ([model-comparison-stage-a.md](model-comparison-stage-a.md)) compared
Qwen 2.5 7B with 72B. This round widens Stage A of
[DECISIONS.md §12](../DECISIONS.md) to pick one **small** model (8–14B, fits a
24 GB GPU under vLLM) and one **large** model (30–70B, fits one 48 GB L40S,
4-bit allowed) for Stage B. Every contradicted chapter-summary sentence, with
the judge's reason, is in
[model-comparison-round-2-contradicted.md](model-comparison-round-2-contradicted.md).

## Recommendation for Stage B

**Decided 2026-11-09** ([DECISIONS.md §12](../DECISIONS.md)): lead with
Llama 3.3 70B. Use Qwen3 14B only when no `g6e.xlarge` capacity can be found.

- **Small: `Qwen/Qwen3-14B-FP8` (Qwen3 14B, thinking off).** It had the fewest
  contradicted sentences of the small models in both runs (8 and 10, against
  28 to 34 for the current Qwen 2.5 7B). That is close to the large models.
  Runner-up: Gemma 3 12B (13 and 15).
- **Large: `casperhansen/llama-3.3-70b-instruct-awq` (Llama 3.3 70B, AWQ).**
  It had the fewest of any model in both runs (0 and 4, against 8 and 5 for
  Qwen 2.5 72B). It was also about 4× cheaper than Qwen 2.5 72B on OpenRouter,
  and twice as fast (13 s against 27 s per call). Runner-up: Qwen 2.5 72B AWQ.
- No model leaked a spoiler in either run. Coverage doesn't separate them.

Two cautions:
- **Qwen3 14B and the two 70B-class models are within noise of each other.**
  Under DECISIONS.md's rule (keep the smaller model unless it has a spoiler or
  at least 2 more factual errors), Stage B may well keep Qwen3 14B.
- **OpenRouter served all of them in FP8 or better**, not at the 4-bit the
  70B model needs on the L40S. Stage B is the first test of Llama 3.3 70B at
  AWQ 4-bit.

## Setup

- **Text:** the same as round 1. Oz books 1–2 (48 chapters) and *Monte Cristo*
  ch 1–34. Prompts `summaries-v5` (with the rollup check) and judge prompt
  `support-v1`.
- **Judge:** `deepseek/deepseek-v3.2`, pinned to AtlasCloud (FP8).
- **Hosts pinned.** Each model was sent to one OpenRouter host with
  `provider: {order: [host], allow_fallbacks: false, require_parameters: true}`
  (new: `tome.llm.client.pin_host`, used by `tome compare`, off for everything
  else). The pack's run stats record the host that served each call. Every
  call in both runs went to its pinned host.
- **Thinking off** (new: `tome/llm/models.py`). No reasoning text reached a
  summary: every pack was searched for `<think>`, `/no_think`, `analysis` and
  `Thinking Process`. The summaries' `max_tokens` limits still apply.
  - *Qwen3:* the `/no_think` soft switch at the end of the system prompt
    leaves an empty think block (1 reasoning token per call). OpenRouter's
    `reasoning: {enabled: false}` did **not** turn thinking off on DeepInfra,
    and neither did `chat_template_kwargs`.
  - *Qwen3.5:* `reasoning: {enabled: false}` works on every host tried. It
    has no soft switch.
  - *gpt-oss:* low effort, plus 2,048 tokens of `max_tokens` headroom, since
    reasoning tokens count against the limit. It used about 150 reasoning
    tokens per call. 3 replies in 4 packs were still cut off and retried
    shorter, about the same rate as the other models.
- **Two full runs** (`data/compare/round2-run1` and `round2-run2`, not
  committed), run at the same time. Reproduce with:

  ```
  uv run tome corpus fetch oz monte-cristo
  uv run tome compare --target oz --target monte-cristo --out data/compare/round2-run1 \
    --model qwen/qwen-2.5-7b-instruct --model qwen/qwen3-14b --model qwen/qwen3.5-9b \
    --model google/gemma-3-12b-it --model mistralai/ministral-14b-2512 \
    --model openai/gpt-oss-20b --model qwen/qwen-2.5-72b-instruct \
    --model meta-llama/llama-3.3-70b-instruct --model qwen/qwen3-32b
  ```

  A run takes about 75 minutes, mostly waiting on Qwen 2.5 72B, Qwen3 32B and
  Gemma 3 12B (25–27 s per call on their hosts).
- **Cost:** $5.37 in all ($2.61 and $2.62 for the two runs, $0.14 for a
  5-chapter trial). The judge was about two thirds of it, at about $0.09 per
  pack. AtlasCloud rate-limited the judge when both runs ran at once. 24
  judgments still failed after three tries, and a rerun filled them in
  (`tome compare` reuses packs and judgments it already has).

| Candidate | Size class | OpenRouter host | Fits the pod? |
|---|---|---|---|
| `qwen/qwen-2.5-7b-instruct` (baseline) | small | Phala (only host) | yes, bf16 ~15 GB |
| `qwen/qwen3-14b` | small | DeepInfra FP8 | yes, official FP8 ~16 GB |
| `qwen/qwen3.5-9b` | small | Parasail bf16 | yes, bf16 ~19 GB; needs vLLM ≥ 0.17 |
| `google/gemma-3-12b-it` | small | DeepInfra bf16 | yes, with FP8 on load (bf16 is ~24 GB) |
| `mistralai/ministral-14b-2512` | small | Mistral (only host) | yes, released FP8 ~14 GB; needs vLLM ≥ 0.12 |
| `openai/gpt-oss-20b` | small | CoreWeave FP4 (MXFP4) | yes, MXFP4 ~13 GB |
| `qwen/qwen-2.5-72b-instruct` (baseline) | large | DeepInfra FP8 (only host) | yes, AWQ ~40 GB, tight |
| `meta-llama/llama-3.3-70b-instruct` | large | DeepInfra FP8 ("turbo") | yes, AWQ ~40 GB, tight |
| `qwen/qwen3-32b` | large | DeepInfra FP8 | yes, AWQ ~19 GB |

All nine are on OpenRouter and in vLLM's model registry, so none was dropped.
Two hosts were swapped after a trial: DeepInfra's shared pool returned 429s
for `qwen3.5-9b` and `gpt-oss-20b`. SiliconFlow's `gpt-oss-20b` was also
rejected, because it put the word "analysis" (a reasoning channel name) in a
structured reply.

## Results

The ranking is by **contradicted sentences in chapter summaries**, the signal
that held across round 1's runs. Each cell shows run 1 / run 2. "Rate" is per
100 chapter-summary sentences. Support is the share of sentences the judge did
not flag at all. Leaks and coverage are listed per run.

### Oz, books 1–2 (6 spoiler cases, 6 coverage cases)

| Model | Contradicted | Rate | Leaks | Coverage full | Support, chapters | Support, rollups | Contradicted, rollups | Cost per pack |
|---|---|---|---|---|---|---|---|---|
| Llama 3.3 70B | **0 / 3** | 0.0 / 0.7 | 0, 0 | 5, 5 | 69% / 68% | 70% / 63% | 1 / 0 | $0.036 |
| Qwen3 32B | 5 / 4 | 1.0 / 0.9 | 0, 0 | 4, 5 | 71% / 73% | 67% / 64% | 5 / 2 | $0.032 |
| Qwen 2.5 72B | 6 / 4 | 1.0 / 0.7 | 0, 0 | 5, 5 | 74% / 61% | 64% / 50% | 1 / 2 | $0.133 |
| Gemma 3 12B | 7 / 4 | 1.4 / 0.8 | 0, 0 | 4, 5 | 69% / 63% | 56% / 54% | 4 / 1 | $0.031 |
| Qwen3 14B | 5 / 8 | 1.0 / 1.6 | 0, 0 | 4, 4 | 69% / 61% | 79% / 68% | 3 / 3 | $0.040 |
| Ministral 14B | 11 / 5 | 1.9 / 0.9 | 0, 0 | 5, 4 | 66% / 67% | 43% / 49% | 4 / 2 | $0.069 |
| Qwen3.5 9B | 10 / 12 | 1.6 / 1.8 | 0, 0 | 5, 5 | 69% / 72% | 61% / 67% | 5 / 3 | $0.045 |
| Qwen 2.5 7B | 14 / 20 | 3.5 / 5.0 | 0, 0 | 4, 5 | 63% / 65% | 65% / 77% | 10 / 5 | $0.032 |
| gpt-oss 20B | 18 / 17 | 3.6 / 3.4 | 0, 0 | 3, 4 | 65% / 64% | 79% / 85% | 8 / 4 | $0.017 |

Every model missed `oz-c01` (Tip is Ozma, in the late rollups). The
`oz-c04` (recap names the companions) and `oz-c06` (recap keeps the
beginning) misses came and went between runs.

### Monte Cristo, ch 1–34 (11 spoiler cases, 11 coverage cases)

| Model | Contradicted | Rate | Leaks | Coverage full | Support, chapters | Support, rollups | Contradicted, rollups | Cost per pack |
|---|---|---|---|---|---|---|---|---|
| Llama 3.3 70B | **0 / 1** | 0.0 / 0.3 | 0, 0 | 6, 6 | 57% / 68% | 67% / 64% | 0 / 1 | $0.039 |
| Qwen 2.5 72B | 2 / 1 | 0.5 / 0.3 | 0, 0 | 6, 6 | 59% / 60% | 58% / 76% | 2 / 0 | $0.154 |
| Qwen3 14B | 3 / 2 | 0.8 / 0.5 | 0, 0 | 6, 6 | 60% / 56% | 78% / 76% | 1 / 4 | $0.048 |
| Ministral 14B | 5 / 5 | 1.3 / 1.3 | 0, 0 | 6, 6 | 48% / 47% | 62% / 43% | 1 / 0 | $0.082 |
| Qwen3 32B | 7 / 3 | 2.1 / 0.9 | 0, 0 | 6, 6 | 56% / 58% | 71% / 76% | 3 / 0 | $0.032 |
| Gemma 3 12B | 8 / 9 | 2.3 / 2.5 | 0, 0 | 6, 6 | 60% / 56% | 75% / 71% | 1 / 4 | $0.030 |
| Qwen 2.5 7B | 13 / 9 | 4.0 / 2.8 | 0, 0 | 6, 6 | 49% / 51% | 66% / 76% | 1 / 8 | $0.039 |
| Qwen3.5 9B | 13 / 16 | 3.3 / 4.1 | 0, 0 | 6, 6 | 61% / 63% | 52% / 51% | 8 / 8 | $0.044 |
| gpt-oss 20B | 18 / 14 | 5.5 / 4.4 | 0, 0 | 6, 6 | 48% / 50% | 81% / 91% | 6 / 12 | $0.017 |

Every pack missed the same five coverage cases: `mc-c01`, `mc-c02` and `mc-c05`
(also missed in round 1), and `mc-c09` and `mc-c11`, whose horizons are past
ch 34.

### Both targets together, and the run-to-run spread

Contradicted sentences in chapter summaries, Oz plus Monte Cristo:

| Model | Run 1 | Run 2 | Spread | Mean |
|---|---|---|---|---|
| Llama 3.3 70B | 0 | 4 | 4 | **2.0** |
| Qwen 2.5 72B | 8 | 5 | 3 | 6.5 |
| Qwen3 14B | 8 | 10 | 2 | **9.0** |
| Qwen3 32B | 12 | 7 | 5 | 9.5 |
| Ministral 14B | 16 | 10 | 6 | 13.0 |
| Gemma 3 12B | 15 | 13 | 2 | 14.0 |
| Qwen3.5 9B | 23 | 28 | 5 | 25.5 |
| Qwen 2.5 7B | 27 | 29 | 2 | 28.0 |
| gpt-oss 20B | 36 | 31 | 5 | 33.5 |

Per target, the spread between runs was 0 to 6 sentences.

**Pinning a host did not make runs repeatable.** Even chapter 1, which gets
identical input in both runs, came back word for word the same for only 2 of
the 9 models (Qwen3 14B and gpt-oss 20B, on both targets). Past chapter 1, at
most one more chapter in a pack matched, since each chapter summary feeds the
next prompt. At temperature 0 the hosts are still not deterministic (batching and
FP8 kernels), so pinning removes the host-to-host differences but not this.
The spreads are a little smaller than round 1's unpinned ones (72B: 6 to 12 on
Oz then, 4 to 6 now), but two runs are too few to say that pinning reduced
the noise.

## What it shows

1. **The models fall into three groups, and the gaps between groups are wider than the noise.**
   - *Few errors:* Llama 3.3 70B, Qwen 2.5 72B, Qwen3 14B and Qwen3 32B, at
     0–12 per run.
   - *Middle:* Ministral 14B and Gemma 3 12B, at 10–16.
   - *Many:* Qwen3.5 9B, Qwen 2.5 7B and gpt-oss 20B, at 23–36.

   Within the first group, only Llama 3.3 70B is ahead in both runs, and only
   by a few sentences.
2. **Llama 3.3 70B was also among the most careful in other ways.** It had
   among the fewest unsupported sentences on Monte Cristo (118 and 83; Qwen3
   32B had 112 and 115, the others 117–183). It was the only model with no
   names the text hadn't used yet left in any of its four packs.
3. **Qwen3 14B is the clear small pick.** It beat Gemma and Ministral in both
   runs, and it is roughly level with Qwen 2.5 72B, a model five times its
   size. Thinking stays off with a prompt switch that works the same on vLLM.
4. **gpt-oss 20B scores best on rollup support (79–91%) but worst on
   chapters.** Its chapter summaries make confident slips, and its rollups
   compress those into fewer, safer sentences. Chapter summaries are what the
   app shows, so it ranks last.
5. **Ministral 14B's rollups are the least supported (43–62%).** It also
   writes in the present tense, which the prompt says not to do. Qwen3.5 9B,
   newer than Qwen3 14B, is clearly worse here. It is also a hybrid-attention
   model that would need vLLM ≥ 0.17.
6. **Spoilers and coverage don't separate the models.** There were no leaks
   in 36 packs. Coverage misses are the same few cases for everyone.

## Spot-check of the judge

These are 9 *contradicted* flags on the two recommended models, checked
against the chapter text. Llama 3.3 70B's flags are all 4 of its chapter
flags.

| Model, where | Summary says | Text | Verdict |
|---|---|---|---|
| Llama, Oz b2 ch19 | Tip's wish "seemed to have no effect, and he experienced intense pain" | The pain comes first; "I wish I'd never swallowed that pill!" stops it at once | real error |
| Llama, Oz b2 ch17 | chopping the royal palm is "punishable by death and imprisonment" | "to be killed seven times and afterward imprisoned for life" | judge too strict (fair compression) |
| Llama, Oz b2 ch7 | "Due to a language barrier, the Scarecrow called for an interpreter" | Both only *believe* they speak different languages | borderline (a belief told as fact) |
| Llama, MC ch9 | Villefort says Dantès is "a great criminal" and he can do nothing | Matches the text; the judge's own reason ends "No flag needed here" | judge mistake |
| Qwen3 14B, Oz b2 ch16 | "The Tin Woodman suggests they must escape through the air" | The Scarecrow says it, and proposes that the Tin Woodman build the machine | real error |
| Qwen3 14B, Oz b1 ch8 | "The raft breaks apart" | The current sweeps the raft away while the Scarecrow is left on his pole | real error |
| Qwen3 14B, MC ch33 | "Cucumetto, a bandit, killed Teresa and her father" | The victim is Rita; Teresa is alive, Vampa's betrothed | real error |
| Qwen3 14B, Oz b1 ch15 | Oz "admits he has no real magical powers and cannot fulfill their wishes, but he promises to try" | He admits being a humbug, then promises to help | judge too strict (roughly fair) |
| Qwen3 14B, Oz b2 ch7 | Jellia "misinterprets" Jack's words | She mistranslates on purpose, as a joke | real, minor |

About 5 in 9 are real errors, 2 are fair compressions, 1 is borderline and 1
is a plain judge mistake. That is consistent with round 1: the counts rank
the models, but they are not error rates. Qwen3 14B's Monte Cristo ch33 slip
(who was killed) is the kind Stage B should catch.

## Serving notes for Stage B (vLLM on `g6e.xlarge`)

`scripts/gpu_pod.py` now has a preset for each candidate. Use
`--model <preset>`, and `setup --vllm-version` for models that need a newer
vLLM. On the pod, tome's `--model` is the Hugging Face id (for example
`--model Qwen/Qwen3-14B-FP8`). tome switches thinking off per request
(`tome/llm/models.py`), so the server needs no extra flags for that.

- **Qwen3 14B (small):** preset `qwen3-14b`, which serves `Qwen/Qwen3-14B-FP8`.
  - Official FP8 weights, about 16 GB, so it also fits a 24 GB GPU.
  - Supported by the pod's current vLLM 0.11.0.
  - Native context is 32k. The pod default of `--max-model-len 16384` is
    enough: the largest summary call in these runs was about 11.4k tokens.
  - Thinking is off through `/no_think` in the system prompt. vLLM also gets
    `chat_template_kwargs: {enable_thinking: false}`.
  - If a reply ever carries a `<think>` block, the client strips it.
- **Llama 3.3 70B (large):** preset `llama-3.3-70b`, which serves
  `casperhansen/llama-3.3-70b-instruct-awq`.
  - AWQ 4-bit, about 40 GB of weights on the 48 GB L40S.
  - The preset adds `--kv-cache-dtype fp8`, because a bf16 cache for 16k
    tokens (about 5 GB) doesn't fit beside the weights.
  - If vLLM still reports too few KV blocks:
    1. add `--vllm-arg=--max-model-len=12288` (the longest Llama call here was
       about 10.4k tokens);
    2. then try `--vllm-arg=--enforce-eager`.
  - No thinking mode. Llama 3.3 is not gated as an AWQ community checkpoint;
    the official Meta repo is.
  - This is the riskiest fit, so run a 5-chapter trial (`--max-chapters 5`)
    first.
- **Runners-up:**
  - `gemma-3-12b`:
    - gated, so it needs `HF_TOKEN`;
    - FP8 on load, which needs an Ada GPU such as the L40S or L4;
    - images are turned off.
  - `qwen2.5-72b`: AWQ, with an FP8 KV cache, as in round 1.
- **The pod's vLLM stays at 0.11.0**, since both recommended models run on it.
  - `--vllm-version 0.33.0` (the current release) is needed only for Qwen3.5
    (≥ 0.17) or Ministral 3 (≥ 0.12). Above 0.11 the script drops the
    `transformers<5` pin.
  - The version bump is untested on the pod.

## Follow-up: do two drafts agree on their errors? (2026-11-09)

The question: could we write each chapter summary twice and keep only the
sentences both drafts agree on? `scripts/agreement.py` tested this on the two
runs we already have.
- **Method:** for every chapter, a checker (`deepseek/deepseek-v3.2`, pinned
  to AtlasCloud) read each sentence of one run's summary next to the other
  run's summary of the same chapter. It answered *agree*, *conflict* (the
  other draft says something incompatible) or *absent*, in both directions.
  The answers were then crossed with the support judge's flags.
- **Size:** 9 models, 2 targets, 16,500 sentences.
- **Cost:** $0.34. 61 sentences got no verdict and are left out.

| Model | Judged contradicted | Dropped (agree-only filter) | Dropped (conflict-only filter) | Unflagged sentences | Dropped (agree-only filter) | Dropped (conflict-only filter) |
|---|---|---|---|---|---|---|
| Qwen 2.5 7B | 54 | 41 (76%) | 34 (63%) | 842 | 265 (31%) | 163 (19%) |
| Qwen3 14B | 17 | 8 (47%) | 6 (35%) | 1,071 | 208 (19%) | 119 (11%) |
| Qwen3.5 9B | 50 | 28 (56%) | 24 (48%) | 1,410 | 312 (22%) | 164 (12%) |
| Gemma 3 12B | 28 | 18 (64%) | 13 (46%) | 1,055 | 270 (26%) | 152 (14%) |
| Ministral 14B | 26 | 17 (65%) | 13 (50%) | 1,145 | 213 (19%) | 112 (10%) |
| gpt-oss 20B | 65 | 35 (54%) | 30 (46%) | 973 | 312 (32%) | 166 (17%) |
| Qwen 2.5 72B | 13 | 4 (31%) | 3 (23%) | 1,238 | 179 (14%) | 101 (8%) |
| Llama 3.3 70B | 4 | 2 (50%) | 1 (25%) | 1,017 | 143 (14%) | 82 (8%) |
| Qwen3 32B | 17 | 8 (47%) | 5 (29%) | 1,068 | 191 (18%) | 105 (10%) |
| **All** | **274** | **161 (59%)** | **129 (47%)** | **9,819** | **2,093 (21%)** | **1,164 (12%)** |

The "agree-only" filter drops any sentence the other draft doesn't agree
with. The "conflict-only" filter drops only sentences the other draft
contradicts. Per-model counts (`data/compare/agreement.md`) are not
committed.

**What it shows:**

1. **Agreement is a poor filter.**
   - The agree-only filter removes about 3 in 5 judged errors.
   - It also throws away 1 in 5 sentences the judge found nothing wrong
     with, about 13 good sentences for every error.
   - For Llama 3.3 70B, it drops 2 of its 4 judged errors and 143 good
     sentences.
   - Dropping only conflicts is gentler, but still costs about 9 good
     sentences per error caught.
2. **Two in five judged errors appear in both drafts.** The other draft
   agreed with 113 of 274. Some of these are judge false positives; the
   spot-check above found about 4 in 9 are. The rest are a model misreading
   the same passage the same way twice. Only a check against the chapter
   text can catch those, so agreement can't replace that check.
3. **Some disagreement comes from the setup, not the model.** The two runs'
   drafts of a chapter had different rolling context, because their earlier
   summaries differed. Two drafts from the same context would probably
   disagree less. They would still share the systematic errors in point 2.
4. **Agreement is a cheap stability measure.** The stronger models' clean
   sentences were dropped least: Llama and Qwen 2.5 72B lost 14%, against
   31–32% for Qwen 2.5 7B and gpt-oss.

**Verdict:** don't build a two-draft consensus step. Spend the effort on
checking each chapter summary against its own text (PLAN.md Phase 1). At
most, a conflict between drafts could be one low-weight signal in the
review queue.
