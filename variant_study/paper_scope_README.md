# Manuscript response scope

The frozen randomized-instance study contains 1,610 responses from five model
profiles. The manuscript analyzes 1,440 responses: 240 new-instance responses
and 48 same-prompt replicates per profile. A separate set of 170 responses at
seeds retained in the source-course exports remains in the study record but is
excluded from manuscript aggregates because the source-course seed-selection
process is undocumented.

`paper_scope_summary.json` records the included response roles, the excluded
response keys, all affected counts, and SHA-256 hashes of its inputs. No
response was deleted or regraded.

`build_manuscript_scope.py` produced the summary; it also reads a copy of
the outer-brace results that is not included, so it does not run from here.
`recompute_paper_numbers.py` applies its logic to the files of this
repository, and its test runs from here.
