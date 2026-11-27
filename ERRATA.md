# Errata

## Per-response files of the randomized-instance study

The software package that the reviewers of the paper received in August 2026
contained the wrong per-response files. Its `variant_study/results.csv` and
`variant_study/analysis.json` came from a separate regrade, not from the primary
grading run. The regrade unwraps a response enclosed in a redundant pair of
outer braces and grades it again when it earns less than full credit.

Against the primary results, the regrade

- changes nine response scores from 0 to 1, all on two questions whose answer
  is a set: five for GLM-Z1 (three instance responses, two replicate
  responses) and four for GLM-4 (one instance response, three replicate
  responses);
- has different checker outputs for three further responses on one question
  (one from Gemma 4 and two from Qwen3), with unchanged scores.

This repository ships the primary files in `variant_study/` and keeps the
regrade, with its own grader, in
`variant_study/sensitivity/outer_brace_regrade/`. Every number of the
randomized-instance study in the paper was computed from the primary files,
except the outer-brace sensitivity analysis in Appendix F, which reports this
regrade. The correction changes no number in the paper.

The earlier package can be recognised by the SHA-256 of its archive:
`b007bf59a3b278d4b23c7770ea9d6130775e2effd24d2dc7c633b073d3fec21a`.

## Concept-labeling prompt

The same earlier package shipped, as the labeling prompt, the prompt of an
earlier 200-question reference-sample run (SHA-256
`6cfde62b93c73bb7e1119da72fd6407a71201f421b307426e41c7d9690d68f8e`). The released corpus-scale labels were
produced with a different prompt (SHA-256 `7f018d8f44ba57828b35ed4df5721182abde6bc3dcbbafaa3d8b8203c43328da`), which
the run manifest of that package already named. This repository ships the
prompt of the corpus-scale run in `labeling/corpus_run/`.
