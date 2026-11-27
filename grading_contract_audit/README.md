# Grading-contract audit

This audit describes the Potential Response Tree (PRT) structure of the 1,604
STACK questions. It does not rank grading systems or claim that another
program could not reproduce an authored contract.

A question satisfies `direct_equivalence_only` when every graded answer field
maps one-to-one to a PRT containing one terminal `AlgEquiv` node, with
autosimplification enabled, no test options, and binary full/zero scores. Of
the 1,603 questions with at least one PRT, 867 satisfy this definition and 736
(45.9%) do not.

The overlapping component features include branching (408 questions), a
non-`AlgEquiv` answer test (367), a derived student-response expression (278),
test options (223), and an explicit partial-credit score (152). Input-format
constraints and authored feedback are reported separately in `summary.json`
and do not increase the primary 45.9% count.

The response-level checker diagnostic uses the 1,440 responses defined in
`../variant_study/paper_scope_summary.json`. Normalized exact matching covers
all 1,366 decisive STACK outcomes. The restricted Maxima-to-SymPy conversion
bridge supports 845; unsupported expressions receive no verifier verdict.
Conditional on bridge coverage, agreement with STACK is 97.0% for SymPy and
97.2% for Math-Verify. These figures describe the bridge's supported domain;
they do not replace replay of question-specific PRT logic.

`analyze_grading_contracts.py` computes the features from the source exports,
which are not included; its test runs from this repository.
