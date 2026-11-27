# Contract-focused pilot: results (post hoc)

Collected on 2026-09-16 on a local GPU server; graded and analyzed on the
pinned local STACK engine (`grade_manifest.json` records engine image IDs and
file hashes). Grid complete: 20 questions x 4 instances x 5 profiles = 400
responses, no transport failures, no holes.

**Scope:** post hoc pilot; 20 single-field questions whose contracts use
non-AlgEquiv tests; counts of responses and of questions in both directions;
not a prevalence estimate; separate from the 60-question study.

## Prespecified counts (PROTOCOL §6; decisive rows = STACK correct or wrong)

Decisive rows: 338 of 400 (36 partial credit, 15 format failures, 11 invalid).

| Comparator | Covered | STACK grants, comparator denies | Comparator accepts, STACK denies |
|---|---:|---:|---:|
| Normalized exact match | 338 / 338 | 139 responses, 14 questions | 0 |
| SymPy bridge | 326 / 338 | 22 responses, 3 questions | 9 responses, 3 questions |
| Math-Verify bridge | 326 / 338 | 16 responses, 1 question | 9 responses, 3 questions |

By family (SymPy: covered, grants/denies, accepts/denies): form 153, 16 (1 q),
9 (3 q); int 53/56, 1 (1 q), 0; numerical 61/70, 5 (1 q), 0; subst 59, 0, 0.

Per profile, descriptive only (full / zero / partial 0.5 / format failure /
invalid; each row sums to 80): GPT-5 61/11/8/0/0; Gemma 4 56/16/8/0/0; Qwen3
49/19/8/0/4; GLM-4 49/23/7/0/1; GLM-Z1 45/9/5/15/6. GLM-Z1's format failures
are the strict `<answer>` contract, as in the main study. No ranking
claim is made.

## Attribution of every comparator-level disagreement (`disagreement_inspection.csv`)

**Comparator accepts, STACK denies (9 responses, 3 questions, 4 profiles:
Qwen3 4, Gemma 2, GLM-4 2, GLM-Z1 1).** All three contracts begin with
`EqualComAss` and fall through to an `AlgEquiv` node that awards 0. Six
responses are unevaluated or unreduced expressions; three are mathematically
equivalent complex roots in a different arrangement, rejected by the authored
form comparison. These are disagreements with the contract, not errors by the
comparators.
- *Zahlen: Potenzen (4)*: `4*2`, `6*5`, `3*5` submitted for `8`, `30`, `15`
  (Qwen3). Algebraically equal, not the evaluated form the contract demands.
- *Zahlen: Rationale Zahlen – Addition (1)*: `(4/5)+(8/6)` for `32/15`,
  `(6/7)+(10/8)` for `59/28` (GLM-4 2, GLM-Z1 1). Unreduced sums.
- *C_LFZ_Nullstelle_z^3*: `(5*sqrt(3)+5*%i)/2` for `(5*%i)/2+(5*sqrt(3))/2`
  (Gemma 2, Qwen3 1). Equal value in a different arrangement.

**STACK grants, comparators deny (SymPy 22 responses, 3 questions), split
into a conversion limitation and two contract effects.**
- *C_LFZ_z^4 I* (16, all Math-Verify forward disagreements): a conversion
  limitation, not a `FacForm` effect. The question sets `complexno = j` and
  instructs learners to use `j`; the bridge reads `j` as a free symbol. Reading
  `j` as the imaginary unit makes all 16 responses equivalent to their teacher
  answers (checked after grading; no frozen verdict changed). Disclosed, but kept
  separate from PRT behaviour.
- *INT: Skript Trapezregel* (5): `NumAbsolute` with tolerance 5e-7 accepts
  rounded decimals (1.711248 vs 1.71124837943); SymPy compares exactly;
  Math-Verify accepts.
- *INT_PI: algebr. Gleichung* (1): `Int` accepts any name for the constant of
  integration (`C` vs `c`); SymPy does not; Math-Verify accepts.

**Exact match only (139 responses, 14 questions):** reordering, spacing,
constant naming, and equivalent arrangements that the authored tests accept.

## Addition after the prespecified analysis

The protocol's decisive set excludes partial scores. 36 responses (two
`AlgEquiv|Int` questions, 18 each, all five profiles) received 0.5: the
`Int` node fails without an integration constant and the next node awards
+0.5 for a correct derivative. Both comparators deny all 36 (the teacher answer
carries `+c`). This is reported separately and changes no prespecified count.
The 60-question study contained no partial score; this pilot does.
Three GLM-Z1 partial answers write Euler's constant as bare `e`, which the
bridge reads as a variable; with `e` as Euler's constant all 36 have the
teacher answer's derivative and no free constant (post hoc check; frozen
scores unchanged).

## Why 26 responses are neither full nor zero credit

Every one was traced against the pinned engine, and a specific cause was found
for each. Diagnostic probes were graded; no recorded result was altered and
the table above is unchanged (`reproductions/validation_fix_20260916/`).

**11 STACK-ungradable, four distinct causes.**

Each was re-submitted to STACK's `/validate` endpoint, which returns the message
a student would see. These are STACK's own words, not our inference
(`reproductions/validation_fix_20260916/stack_validation_messages.json`).

| STACK's validation message | n | Verdict |
|---|---:|---|
| "Forbidden operator: *." | 6 | authored contract |
| "round: expected exactly 1 arguments but got 2" | 2 | model error |
| "You seem to be missing * characters" | 1 | model error |
| "CAS failed to return any data due to timeout." | 2 | undetermined, see below |

The six are all *FTN_QUAD: Funktionswert*, which asks the learner to compute a
function value. Its author forbade the multiplication operator so the answer
cannot be the substituted expression. Probed at seed 9201, teacher answer 23:
`3*(-4)^2+8*(-4)+7` and `3*4` are refused at validation, `12` validates, and
`23` earns full credit. The models submitted the substitution instead of the
value. This is form enforcement at the *input* layer, before any answer test
runs, and no generic comparator has an equivalent.

The two `float(...)` cases are the one place a mathematically correct answer is
lost: removing the wrapper gives both full credit. STACK reports them as a CAS
timeout, but that label does not fit the evidence: the call returns in 0.16 s,
raising the limit from 10 s to 60 s changes nothing, and the same Maxima
evaluates the expressions directly without difficulty. The mechanism is
undetermined. On this input `float(` is refused while
`1.1`, `sqrt(2)`, `exp(1)`, `sin(1)`, `log(2)`, `round(1.1)`, `sum(k,k,1,3)`,
`ev(1.1)`, `floor(1.1)` and `max(1,2)` all validate on the same input, which
sets `forbidfloat=0`. Whether this holds for every STACK deployment and input
configuration was not tested; the finding is scoped to this question on the
pinned build. It is a limitation.

**15 format failures, all GLM-Z1.** None contains an `<answer>` tag. Fourteen
stopped normally after emitting a bare `answer` line instead of the tagged
form; one reached the token limit without a final answer. This is the same
prespecified output-contract failure as in the main study, not a grading
problem.

**The Maxima backend is not implicated for nine of the eleven.** Those causes
lie in the question's input options, Maxima's function arity, or missing
multiplication signs, none of which depends on which server evaluates. For the
two `float(...)` cases the mechanism is undetermined, so a backend difference
is not excluded; it was not tested.

## Scope

The grading and diagnostic functions are those of the main study, reused
without change; the question selection is new, restricted to single-field
non-AlgEquiv contracts whose four teacher answers the conversion bridge can
parse. Comparator coverage (326 of 338) is therefore conditional on that
selection and is not general coverage of richer contracts.

## Deviations

`qwen3:32b` was served from a newer library build (digest `030ee887…`, July
`e1c9f234…`, July manifest no longer served). Gemma 4, GLM-4, GLM-Z1 are
byte-identical to July; GPT-5 is the pinned snapshot, added to the four
local profiles before collection.

## Reproductions

1. Independent recount from `results.csv` with a separate implementation
   (pandas): every count above matches `analysis.json`.
2. Fresh re-grade of all 400 answers through the pinned engine and both
   bridges, compared cell by cell: 400 rows, zero differing cells in status,
   score, sympy_eq, math_verify_eq, string_eq. Evidence preserved in
   `reproductions/regrade_20260916/` (results, manifest, comparison); recount
   script `reproductions/recount_20260916.py`.
