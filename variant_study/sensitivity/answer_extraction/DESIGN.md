# GLM-Z1 response-extraction sensitivity audit

## Status and purpose

This is a post hoc sensitivity analysis. It does not replace the primary
analysis. The protocol required one
Maxima expression in `<answer>...</answer>` and prespecified a completed
response without that wrapper as `format_failure`; such responses were not
regenerated.

The audit asks how the GLM-Z1 result changes when deterministic repairs recover
an expression from malformed wrappers. It uses the existing raw responses and
does not make new model calls.

## Frozen inputs

- Model responses: `variant_study/answers.jsonl`
- Rendered instances: `variant_study/instances.jsonl`
- Primary grading: `variant_study/results.csv`
- Protocol: `variant_study/PROTOCOL_frozen.md`
- Grading client: `variant_study/stack_client.py`; the source exports of the
  corpus (not included)
- STACK and GoeMaxima: the image digests recorded in the frozen response log

The audit checked the hashes of its inputs before grading. The audit covers all 32 GLM-Z1
`format_failure` rows. The manuscript scope contains 31 because the archived
stored-instance row is excluded from manuscript aggregates.

## Extraction policies

1. `strict`: preserve the primary classification; perform no recovery.
2. `closing_tag`: recover only outputs that start with the literal marker
   `answer` and retain a trailing `</answer>`.
3. `bare_marker`: recover any output that starts with `answer`; remove an
   optional following `>` and an optional trailing `</answer>` or `$`.
4. `single_expression`: apply `bare_marker`, and additionally accept the sole
   nonempty line from an otherwise unmarked response.

Each recovered candidate is graded through STACK against the same question,
seed, input field, and authored PRT used in the primary analysis. A recovered
candidate is not assumed correct merely because it can be parsed.

## Interpretation boundary

The strict policy estimates the complete deployed model profile, including
compliance with the requested output contract. The tolerant policies estimate
answer content after deterministic wrapper repair. They are sensitivity
analyses, not corrections to a prespecified parser.

