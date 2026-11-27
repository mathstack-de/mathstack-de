# Known-Verdict Grading Sanity Check

This artifact records a hand-constructed stress suite for symbolic answer
checking. The suite contains 44 expression pairs:

- 29 pairs with a fixed equivalent verdict;
- 10 pairs with a fixed non-equivalent verdict; and
- 5 unscored diagnostic probes whose behavior depends on assessment
  conventions.

Five equivalent forms are adapted from ASyMOB. The remaining cases cover
algebraic, matrix, unit, antiderivative, and piecewise expressions. The suite
tests this setup and exposes failure modes; it is not a population estimate or
a checker ranking.

## Reported Results

| Verifier | Equivalent accepted | Equivalent missed | False accepts | Unsupported scored pairs |
|---|---:|---:|---:|---:|
| STACK answer tests | 26 | 3 | 0/10 | 0 |
| SymPy 1.14.0 `simplify` | 22 | 5 | 0/8 | 4 |
| Math-Verify 0.9.0 | 21 | 6 | 0/8 | 4 |

The four unsupported scored pairs use physical units. STACK evaluates them
with `ATUnits`; the conversion used for SymPy and Math-Verify does not support
that answer type. The five diagnostic probes are excluded from every fraction.
All three reported verifiers miss at least one tested piecewise identity using
`max`, `min`, or `signum`.

`results.csv` contains every raw outcome, and `rescored_summary.json` reports
the error-aware tally for all five recorded checker configurations. The
additional engineered SymPy and direct Maxima configurations document
conversion behavior and are not presented as a leaderboard.

## Reproduction

The exact engine and scoring conventions are in `GRADING_CONFIG.md`.
With that GoeMaxima service reachable at `http://127.0.0.1:18080/maxima`
(for example, add `ports: ["127.0.0.1:18080:8080"]` to the `maxima` service
of the compose file in the dataset's `GRADING.md`):

```bash
MAXIMA_URL=http://127.0.0.1:18080/maxima \
  python3 run_suite.py --pairs known_verdict_pairs_v2.yaml \
  --out reproduced_results
```

The script requires Python, PyYAML, Requests, SymPy 1.14.0, and Math-Verify
0.9.0. `rescore.py` applies the three-valued tally in which execution errors
never count as correct rejections. `z3_piecewise_proofs.py` contains auxiliary
proofs for the three tested piecewise identities; it needs the `z3-solver`
package.
