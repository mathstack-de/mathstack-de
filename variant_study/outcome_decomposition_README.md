# Outcome decomposition

This post-hoc descriptive analysis separates mixed outcomes across the four
new instances of each randomized question. The primary protocol is unchanged:
every invalid output counts as non-full-credit.

- `mixed_gradable` means that at least one response receives full credit and
  at least one non-full-credit response is gradable by STACK.
- `mixed_invalid_only` means that at least one response receives full credit
  and every non-full-credit outcome is invalid rather than STACK-gradable.

`outcome_decomposition.json` records the classification and the SHA-256 hash
of the frozen response table. The analysis explains the failure modes within
the primary outcome counts; it does not replace them.

`analyze_outcome_decomposition.py` produced the classification;
`recompute_paper_numbers.py` applies its logic to the files of this
repository, and its test runs from here.
