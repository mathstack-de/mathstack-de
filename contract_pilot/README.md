# Post-hoc contract pilot

A post-hoc pilot, reported in Section 6.2 and Appendix I. It reuses the
grading path of the main study on 20 selected questions whose grading
contracts use tests other than `AlgEquiv`: 4 instances and 5 model profiles
per question, 400 responses. It is separate from the 60-question study and is
not a prevalence estimate.

- `PROTOCOL.md`: the protocol, fixed before the first model call.
  `frozen_manifest.json` records the hashes of the files as they were fixed.
- `inputs/`: the candidate pool and the gating that produced it.
  `select_pilot.py`, `selection.csv`, `draw_log.json`: the seeded draw.
- `instances.jsonl`: the 80 instances with prompt and teacher answer.
- `answers.jsonl`: raw model outputs (provider telemetry removed).
- `results.csv`, `grade_manifest.json`, `pilot_grade.py`: STACK verdicts and
  the three secondary diagnostics.
- `analysis.json`, `analyze_pilot.py`, `disagreements.jsonl`,
  `disagreement_inspection.csv`: the prespecified counts and the inspection
  of every disagreement.
- `RESULTS.md`: the written results, including the diagnosis of the 26
  responses without a score (15 format failures and 11 STACK-ungradable
  responses).
- `reproductions/`: an independent recount and regrade, and in
  `validation_fix_20260916/` the validation messages of the responses without
  a score that `RESULTS.md` cites.
- `pilot_run.py`: how the responses were collected.
