# Contract-focused pilot (post hoc)

Status: fixed before the first model call. This pilot is separate from the
60-question study (`variant_study/`) and is never merged into it. It is
reported as a post hoc pilot; it does not estimate corpus-wide prevalence and
makes no leaderboard claims.

## 1. Question

On single-field questions whose authored contract uses a non-AlgEquiv answer
test, how often does the authored STACK contract disagree with a generic
comparator on real model responses, in both directions:
(a) STACK grants full credit, comparator rejects;
(b) comparator accepts, STACK denies.
Every disagreement is attributed to the PRT rule responsible by inspection.
Zero disagreements in either direction is a reportable result.

## 2. Eligibility and gating (already executed; inputs frozen in `inputs/`)

Pool built with the loader and the filters of the main study
(`variant_study/draw.py`: auto-gradable, exactly one `algebraic` input,
`rand*()` in question variables, no images, question text <= 2,500 chars,
not in the expert reference, the worked-solution development sets or the 40
development templates),
with three changes: the answer-test set must contain at least one
non-AlgEquiv test; questions whose only non-AlgEquiv test is `Diff` are
excluded (Diff is algebraic equivalence plus feedback); the 60 study
questions are excluded. Packaged round-trip pass (`roundtrip_ok`) required.
Result: 111 candidates (`inputs/candidates.csv`).

Gating (`inputs/gate_pool.py`, local pinned STACK engine, image IDs identical
to those of the main study): seeds 9201 upward, at most 12 tries, keep a seed only if
render succeeds, a structured teacher answer exists, the teacher answer scores
1.0 at that seed, and the model-facing prompt hash is new. A question passes
with exactly four instances. Result: 104 pass (`inputs/gated_pool.jsonl`).
Comparator coverage: a question is eligible for the draw only if the teacher
answers of all four gated instances are accepted by the allowlisted SymPy
conversion bridge of `variant_study/grade.py` (`inputs/gated_pool_coverage.jsonl`;
94 of the 104 pass). This restriction exists so that comparator verdicts can
exist at all; model responses may still fall outside the bridge, and that
coverage is reported. Excluded by it: inequality answers (`x <= 5`), set
answers, and equation systems.

Families by non-AlgEquiv test: `form` (EqualComAss, SingleFrac, FacForm,
PartFrac, Expanded, CasEqual), `int` (Int), `numerical` (NumAbsolute,
NumRelative), `subst` (SubstEquiv), `other`.

## 3. Draw (once, by `select_pilot.py`, RNG seed 20260916)

20 questions: subst 3, numerical 4, int 5, form 8, drawn in that order
(smallest family first). Within each family the passing candidates are
sorted by `rc_id`, shuffled with the seed, and taken in order, skipping a
question when its topic already has 6 selected questions overall. No
replacements are needed because every candidate is already gated. The four
gated instances of each selected question are the grid: 80 instances.

## 4. Models and inference (frozen)

All five profiles of `variant_study/profiles.json`, options unchanged: the
four local profiles `gemma4:31b`, `qwen3:32b`,
`hf.co/unsloth/GLM-4-32B-0414-GGUF:Q4_K_M`,
`hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M` served by Ollama on a local GPU
server (RTX 6000 Ada 48 GB), and the snapshot-pinned API anchor
`gpt-5-2025-08-07` (reasoning effort medium). The served Ollama digest is
recorded per response and compared with the July digest. Verified before
collection: `gemma4:31b`,
GLM-4 and GLM-Z1 are byte-identical to the July builds; `qwen3:32b` differs
(library tag updated after July; the July manifest is no longer served). That
difference is a documented deviation, not a stop.

Collection (`pilot_run.py`): GPT-5 first, then the local profiles one at a
time. Prompt, system text and answer extraction are those of the main study
(`variant_study/prompt_template.json`), unchanged. A completed
response without `<answer>` tags is a format failure and is never
regenerated. Grid: 20 x 4 x 5 = 400 responses, one call each, no replicates,
no anchors. Transport failures are retried; completed responses are terminal.

Freeze: the protocol and code are fixed first and the draw second;
`freeze.py` then writes `frozen_manifest.json` (the SHA-256 of every frozen
file). `pilot_run.py` refuses to run unless every frozen file matches that
manifest.

## 5. Grading and diagnostics (frozen)

Authoritative: STACK `/grade` on the local pinned engine at the same seed the
model saw, policy `raw-v1+brace-off` (answer graded exactly as submitted; no
brace normalization; the literal response form is what form-sensitive tests
must see). Diagnostics, never authoritative, all against the gated teacher
answer: normalized exact match, SymPy bridge, Math-Verify bridge, using the
functions of `variant_study/grade.py` unchanged, executed with the same
interpreter and library versions as the main study (system `python3`,
SymPy 1.14.0, Math-Verify 0.9.0). Coverage is part of the result.

## 6. Analysis (prespecified)

For decisive rows (STACK correct or wrong): per method, covered n, direction
(a) count, direction (b) count, and the number of distinct questions in each
direction; the same by family and by exact test set. Format-failure and
invalid counts per profile. Per-profile full-credit rates are descriptive
only. Every disagreement row is listed with the question's answer tests and
an inspected `prt_rule` attribution (manual, recorded in
`disagreement_inspection.csv`). Comparison with the 60-question study is
limited to noting that direction (b) could not be attributed there.

## 7. Stop rule and reporting

Results are reported only after collection, grading, two independent
reproductions of every reported count, and the inspection table are
complete. Scope: post hoc pilot; 20 single-field non-AlgEquiv questions;
counts of responses and of questions in both directions; not a prevalence
estimate.
