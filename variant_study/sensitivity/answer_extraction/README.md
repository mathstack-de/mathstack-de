# Findings

The primary analysis is reproducible under its frozen response
contract. A completed response without a valid `<answer>...</answer>` wrapper
was prespecified as a format failure. Under that strict policy, GLM-Z1 receives
full credit on 189/240 fresh responses (78.8%) and has an all/some/none question
partition of 30/27/3.

The result is materially sensitive to deterministic wrapper recovery:

| Policy | Recovered rows | Fresh full credit | All/some/none | Paper-scope format failures |
|---|---:|---:|---:|---:|
| Strict (primary) policy | 0 | 189/240 (78.8%) | 30/27/3 | 31/288 |
| Retained closing tag | 12 | 199/240 (82.9%) | 34/23/3 | 20/288 |
| Literal `answer` marker | 31 | 215/240 (89.6%) | 48/9/3 | 1/288 |
| Single-expression fallback | 32 | 216/240 (90.0%) | 49/8/3 | 0/288 |

STACK awards full credit to 31 of the 32 recovered candidates. In the
manuscript scope, which excludes one archived stored-instance response, 30 of
31 receive full credit and one receives zero credit. The zero-credit candidate
is retained in `per_response.csv`; recovery is therefore not treated as
automatic correctness.

The strict score remains a valid measure of the complete model profile,
including compliance with the requested output format. The tolerant scores
measure mathematical answer content after deterministic wrapper repair. The
difference matters for the interpretation of the GLM failure composition: the
strict contrast is partly an output-contract result.

The main replicate conclusion does not reverse. Under every audited policy,
the post hoc question-bootstrap interval for cross-instance minus same-prompt
disagreement contains zero. The overall five-profile fresh full-credit range
also remains 77.5% to 95.0%, because GLM-4 remains the minimum and GPT-5 the
maximum.

