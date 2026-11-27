# Randomized-instance study: frozen protocol

Status: **collection and reported analysis complete**: 1,610 responses, the
full 322-row grid for each of five retained profiles, and no transport
failures or grid holes. The outer-brace policy of section 6 is not used for
the reported numbers; a regrade under that policy is a separate, labeled
sensitivity analysis.

The protocol and the harness were fixed before the one-time draw (60
templates, 34 anchors, 2 logged candidate replacements). All five profiles
passed the live probe before collection. The 40-template development sample
tuned this harness and is excluded from the confirmatory sample and from all
confirmatory statistics.

## 1. Research questions and claims

- **RQ1 (consistency):** How consistently does a model solve the *same*
  template across fresh random variants (all / some / none of 4)?
- **RQ2 (anchor):** On templates with an author-deployed variant, does
  accuracy on that author-configured instance differ from fresh-variant
  accuracy?
- **RQ3 (grading):** How often do naive string matching, SymPy, and
  Math-Verify disagree with production STACK grading on real model answers?

**Claim discipline:** cross-seed differences are called *variant sensitivity*
only when they exceed the same-prompt replicate variation; otherwise they are
reported as inseparable from decoding variability. An anchor/fresh difference
does not establish contamination, web exposure, or a general direction of
benchmark bias. No leaderboard claims; ranking-stability
statements only. The GLM-4 vs GLM-Z1 comparison is a prespecified ablation
reported as an *association* between reasoning tuning and consistency, never
causal.

## 2. Frame and sampling (held-out, drawn once after this protocol was fixed)

Eligible: STACK, exactly one input of type `algebraic`, answertests
`AlgEquiv` only, `rand*()` in questionvariables, auto-gradable, no images in
the question text, question text ≤ 2,500 chars, **not** in the expert
reference (200 questions), **not** in the worked-solution development sets,
**not** among the 40 development templates.

Draw: **60 templates**, randomly ordered with a maximum of 4 per topic, RNG
seed **20260718**, drawn exactly once by `draw.py` with the fixed
harness. This is a diversity-capped draw, not a proportional stratified sample.
No redraws of templates; a
template that fails instantiation gates is REPLACED by the next eligible
candidate in the shuffled order, with the replacement logged.

Instances per template:
- **4 fresh instances**: seeds drawn sequentially from 9201, 9202, … keeping
  a seed only if the SHA-256 of the canonical system+user payload is new for
  that template and differs from the anchor payload, where present; stop at 4 unique
  or after 12 candidate seeds (then replace the
  template, logged). `questionnote` is never used for uniqueness and never
  enters model-facing records.
- **1 anchor instance** where the template has ≥1 author-deployed seed (first
  deployed seed). k = number of anchor templates, fixed at draw time.

Per-instance preflight gate (all must pass BEFORE any model call):
render → structured teacher answer present (`questioninputs[*].samplesolution`)
→ grade(teacher answer) → `isgradable && isclose(score, 1.0, abs_tol 1e-9)`.

## 3. Models and inference profiles (frozen in profiles.json)

| model | provider | profile source |
|---|---|---|
| gemma4:31b | Ollama (local) | Google card: temp 1.0, top_p 0.95, top_k 64; thinking control token |
| qwen3:32b | Ollama (local) | Qwen card (thinking): temp 0.6, top_p 0.95, top_k 20; `think=true` |
| GLM-4-32B-0414 (Q4_K_M GGUF) | Ollama (local) | vendor card: temp 0.6, top_p 0.95, top_k 40 — explicitly overrides GGUF-embedded 0.2/1.0 |
| GLM-Z1-32B-0414 (Q4_K_M GGUF) | Ollama (local) | vendor card: temp 0.6, top_p 0.95, top_k 40; thinking explicitly triggered |
| gpt-5-2025-08-07 | OpenAI | fixed `reasoning_effort: medium`; snapshot-pinned anchor (stable reference, not "current frontier") |

Source URLs and retrieval dates are stored in `profiles.json`; the exact served
weights are identified by Ollama digest. Kimi-Dev-72B and GLM-4.7-Flash are
excluded (coding specialist without a frozen general-math profile; observed
thinking-channel pathology plus family redundancy). All Ollama
responses store BOTH `message.content` and `message.thinking`. Model digests
captured per run via `/api/show`. Quantization is reported with every model
name. `num_ctx` 32768 and `num_predict` 16384 for all local models. A
one-call-per-profile probe must show that the server accepts the complete option
set and that the visible answer is extractable before the run is cleared.

## 4. Grid (exact; grader refuses anything less)

Per retained model: 60×4 fresh (240) + 34 anchors + replicate arm. Replicate arm: the
first 12 templates in draw order × their first 2 fresh seeds × 2 extra
repeats (+48). **Rows per retained model = 322.** Within each of the first 12
templates, same-prompt disagreement is the mean over six pairwise comparisons
(two prompts × three pairs among three replicates); cross-seed disagreement is
the mean over the six pairs among four base fresh variants. A paired
template-cluster bootstrap estimates their difference. If its 95% interval
contains zero, seed effects are reported as inseparable from decoding
randomness on this frame.

## 5. Response handling (fail-closed)

One prompt shape for all models (German; final answer as a single Maxima
expression in `<answer>` tags). Extraction = last `<answer>` block after
stripping the thinking channel. Terminal statuses:
`correct`, `partial`, `wrong`, `syntax_invalid`, `empty`, `format_failure`
(no tag), `transport_failure` (only after 6 backoff attempts).
**Retries are for transport failures only** — a completed response that
lacks a tag or fails validation is a real model outcome and is never
regenerated. Every call stores: raw content, thinking, done_reason, token
counts, latency, full generation options, prompt sha256, model digest, engine
image digests, harness git commit, timestamp.

## 6. Grading and checker arms

Authoritative: STACK `/grade` on the pinned local container
(stackmaths/stackapi@sha256:03bdfad7…81fba +
mathinstitut/goemaxima@sha256:70e3c838…57e6), same injected seed as the
render the model saw; `correct ⇔ isgradable && isclose(score, 1.0)`; partial
scores preserved. Secondary arms per answer (never authoritative): SymPy equivalence; Math-Verify over LaTeX produced by an
allowlisted Maxima-to-SymPy conversion bridge; and normalized string match
against the structured teacher answer. The bridge accepts only ASCII scalar
arithmetic, rejects attribute access and non-allowlisted calls before parsing,
and runs in a time-limited child process. It is not an OS sandbox.
Conversion/parser failures are errors, never negative verdicts. Raw model text
is never executed through Maxima merely for format conversion. All four
verdicts are logged and conflicting rows are dumped to
`disagreements.jsonl`.

**Post hoc outer-brace sensitivity policy (never the default):** raw answers are graded exactly as submitted under policy
`raw-v1+brace-off`. A separate run may explicitly request
`--brace-normalization outer`. If an initially gradable answer scores below
1.0, that policy removes at most three complete outer `{...}` layers and
resubmits each candidate. A retry is retained only when it improves the STACK
score. This is an alternative answer-interpretation policy, not a correction
to STACK and not proof that the original nested set was mathematically
equivalent to the intended set. Each row stores raw and final status/score,
the accepted candidate, number of layers stripped, and the complete retry
trace. Secondary checkers always see the raw answer.

## 7. Analysis (predeclared)

- Per model: fresh-variant accuracy; anchor accuracy (anchor templates only,
  reported separately — never pooled with fresh).
- Per-template consistency (all/some/none of 4 fresh), per model.
- Ranking stability: model ordering under each single-seed column vs the
  4-seed aggregate.
- Checker-disagreement table with examples; per-checker false-accept /
  false-reject relative to STACK.
- All CIs: nonparametric bootstrap clustered over templates (n=60 units),
  2,000 resamples, 95%. Statuses `syntax_invalid`/`empty`/`format_failure`
  count as not-correct in accuracy; format-compliance rate reported
  separately per model.
- Completeness: analysis runs only on the full 322-row grid for every retained model
  (transport_failure rows count as grid holes → run not complete).

## 8. Kill criteria (per model, evaluated after its first 15 templates)

The gate uses base calls (`rep=0`) for every fresh and available anchor instance
of those 15 templates; replicate calls start only after the gate passes.
Extraction rate < 30% or median latency > 420 s means that model is dropped.
After all five gates, `model_roster.json` records retained and dropped profiles,
their gate statistics, and the profile hash. The grader accepts the complete
322-row grid only for retained models; dropped models are reported as
feasibility failures and never silently removed.

## Changes after the protocol was fixed

- **After the draw, before any scientific model call:** source URLs and
  explicit thinking modes were added, the local context was raised to
  32,768, live profile probes were required, request hashes were made exact,
  the same-prompt/cross-seed comparison was normalized to six pairs per
  template with a paired bootstrap, and the kill gate was made to produce an
  explicit roster. The draw is retained because all 60 selected rows satisfy
  the exact one-input/AlgEquiv frame, all prompt hashes are unique, and none
  of these changes alters selection or rendered instance content.
- **After collection:** answers are graded as submitted with a restricted
  parser (policy `raw-v1+brace-off`; the primary results). The outer-brace
  retry of section 6 is a separate, labeled sensitivity run
  (`sensitivity/outer_brace_regrade/`): 9 of the 1,610 rows change from wrong
  to correct, all on two set-answer templates (GLM-4-32B: 1 fresh base call
  and 3 replicates; GLM-Z1-32B: 3 fresh base calls and 2 replicates); no
  other model and no anchor is affected.
