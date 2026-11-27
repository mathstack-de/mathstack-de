# Sensitivity analysis: outer-brace regrade

This folder holds a second grading pass over the same 1,610 archived
responses (1,440 in the scope of the paper and 170 excluded responses at
source-course seeds), with the same instances and profiles as the primary
results in `variant_study/`. Its grader, the `grade.py` here, is an earlier
version of the primary grader (`grader_commit` in the two
`grade_manifest.json` files) and differs from it in two ways: a response
enclosed in a redundant pair of outer braces is unwrapped and graded again
when STACK gives it less than full credit (`strip_redundant_outer_brace`),
and its conversion bridge for the secondary checkers is an earlier, less
strict one that does not allow some functions the primary bridge allows,
among them `round` and `floor`.
The primary run grades every response exactly as submitted.

Effect against the primary results: nine responses on two set-answer
questions, all from the two GLM profiles, score 1 here and 0 in the primary
run (the unwrapping); the checker columns differ for three further responses
on one question, whose answers use `round` or `floor` (the bridge), with
unchanged scores. The paper reports this regrade only as a named
sensitivity analysis (Appendix F: nine changed scores; on the four
instances, full credit becomes 192 of 240 for GLM-Z1 and 187 of 240 for
GLM-4). All other numbers of the paper and `variant_study/analysis.json` use
the primary results; so does `paper_scope_summary.json`, except its
`brace_sensitivity` counts, which count these nine changed scores.
`ERRATA.md` at the top of this repository documents a correction that
concerns this run.

Files: `results.csv`, `analysis.json`, `disagreements.jsonl`,
`grade_manifest.json` (input and output hashes, recorded when the regrade
ran), `grade.py`.
