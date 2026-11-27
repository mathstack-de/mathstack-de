# Outcome Consistency Across Instances

## Study question

The study measures whether each model profile receives the same STACK
full-credit outcome across separately answered numerical instances of one
randomized question. A model profile is a model together with its quantization,
reasoning mode, and decoding settings. Results therefore describe complete
profiles rather than isolated model weights.

## Question sample

The sample contains 60 randomized STACK questions. Eligible questions have one
algebraic input, use `AlgEquiv` answer-test nodes, contain executable
randomization, are automatically gradable, contain no image in the question
text, and have at most 2,500 question-text characters. Questions in the expert
reference, the worked-solution development set, and an earlier 40-question
development set are excluded.

Questions were randomly ordered with seed 20260718 and a maximum of four per
source-bank category. A question that failed an instantiation check was replaced
by the next eligible question in that fixed order. The draw log records two such
replacements.

## Instances and model calls

Four new instances are generated for every selected question. Candidate seeds
begin at 9201 and are retained only when the resulting model prompt is distinct
from earlier prompts for that question. Before any model call, STACK must render
the instance, expose a structured teacher answer, and award that answer full
credit.

Five prespecified model profiles are evaluated. The candidate roster and
exclusion criteria were fixed before model calls. A prespecified feasibility
check on the first 15 questions retained all five profiles. Every instance is
answered in a separate model call with the profile settings recorded in
`profiles.json` and `model_roster.json`.

## Primary scoring

The primary four-instance set contains 240 responses per profile. A response is
full credit only when it satisfies the fixed extraction policy, is gradable by
STACK, and receives score 1. All other responses remain non-full-credit and are
separately classified as gradable non-full-credit, STACK-ungradable, or format
failure. The manuscript reports the 1,200 four-instance responses and the 240
same-prompt replicate responses, for 1,440 responses overall.

The post hoc outcome decomposition separates question-level mixtures of full
credit, gradable non-full-credit, STACK-ungradable, and format-failure outcomes.
The strict extraction rule remains primary; brace-wrapper results are reported
only as a sensitivity analysis. In this repository, `results.csv` and
`analysis.json` at the top level of `variant_study/` are the primary run;
the outer-brace regrade ships under `sensitivity/outer_brace_regrade/`.

## Same-prompt comparison

The replicate set is the first 12 questions in draw order and the first two new
instances of each. Two additional decodes accompany each original response,
giving three decodes per prompt. For each question, same-prompt disagreement is
the mean of the three pairwise comparisons for each of its two prompts (six
comparisons). Cross-instance disagreement is the mean of all six pairs among
the four new instances. Both reduce outcomes to full credit versus all other
outcomes. Rates are averaged equally across questions, and paired differences
use a 2,000-sample question-clustered bootstrap.

These comparisons are matched by question and number of pairs, not by identical
seed pairs. They measure whether the evaluated calls yield consistent outcomes;
they do not isolate an effect caused specifically by changing the instance.
