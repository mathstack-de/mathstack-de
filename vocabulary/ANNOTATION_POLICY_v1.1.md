# MathStack-DE Annotation Policy - v1.1

**Vocabulary version:** `v1.1_2026-07` (271 concept labels in 22 thematic groups). Concept IDs are authoritative. The complete vocabulary is `concept_vocabulary.v1_1.yaml`.

## Annotation Unit

Assign concept labels to one question. For randomized STACK questions, labels describe the mathematical work required by the question and are intended to apply across its rendered instances.

## Inputs

The annotator receives the learner-visible question text, visible answer options for selection questions, and the worked solution when one is available. Automated annotation uses a recorded seed-specific rendering. Teacher answers, answer keys, question notes, and Potential Response Trees are excluded.

For STACK dropdown, radio, and Boolean inputs, the annotator receives the visible option labels and input types rather than blank input markers. Image pixels are not supplied; available alt text or an explicit image marker represents image content.

## Rules

1. Use only concepts from the closed vocabulary.
2. Tag the mathematical skills needed to solve the question, not topics that
   are merely mentioned or incidental steps in explanatory feedback.
3. Choose the most specific applicable concept. Add a broader concept only
   when that broader skill is independently exercised.
4. Emit each required concept once, even if the skill is used repeatedly.
5. In linear differential equations, tag a characteristic polynomial with the
   ODE concept, not the linear-algebra eigenvalue concept.
6. Tag all required skills and only required skills. There is no target label
   count. An empty set is valid when no vocabulary concept applies.

## Scope Notes

The authoritative wording is stored in the vocabulary's `definition` fields.
The following summaries describe the boundaries most likely to be confused.
Their inclusion does not give these concepts greater priority or expected
frequency. Concepts without an additional scope note remain equally eligible,
and the six general rules apply to every concept.

- **Beweismethode** (LOG.05): establishing truth beyond direct application of
  a definition. Direct definition checks use LOG.08.
- **Nachweis über Definition** (LOG.08): verifying a property directly from its
  definition, not a broader proof method.
- **Kombinatorische Logik** (LOG.03): combinatory logic only. Truth tables use
  LOG.01 and counting problems use PROB.13.
- **Logische Schlüsse** (LOG.06): deriving a new mathematical statement from
  multiple premises, conditions, or intermediate results, or judging whether
  such an inference is valid. Routine substitution, rearrangement, arithmetic,
  or direct formula application alone does not qualify.
- **Berechnung eines Funktionswerts** (FKN.03): evaluating a function is itself
  tested, not incidental substitution inside another method.
- **Graph** (FKN.04): a graph must be read, interpreted, selected, drawn, or
  used.
- **Ausgleichsgerade** (FKN.26): the fitted line is requested, interpreted, or
  used. Performing linear or nonlinear fitting uses LA.12 or NUM.18.
- **Abbildungsvorschrift** (FKN.32): a mapping rule must be constructed from
  stated properties.
- **Nichtlineare transzendente Gleichung** (FKN.33): solving a nonlinear
  equation containing transcendental functions.
- **Linearität einer Abbildung** (LA.16): proving or using linearity of a map or
  operator, not ordinary matrix arithmetic.
- **Erweiterte Koeffizientenmatrix** (LA.19): representing, reading, or using a
  linear system in augmented-matrix form.
- **Gaußsches Eliminationsverfahren** (LA.11): the task is to systematically
  solve a linear system or to carry out a solvability analysis for one. Do NOT
  tag when only the rank or defect of a matrix is to be determined.
- **Elementare Zeilenumformung** (LA.20): a matrix realizing an elementary row
  operation is asked for, or the task asks exclusively for the rank or defect
  of a matrix. Do NOT tag when an inhomogeneous linear system is to be solved.
- **Runden von Dezimalzahlen** (GRDL.21): decimal rounding is itself tested,
  not merely used for display formatting or an incidental intermediate value.
- **Konvergenz** and **Divergenz** (SEQ-LIM.02/.06): use the outcome-specific
  label when convergence behavior of a sequence is analyzed.
- **Gemischte Ableitungsregeln** (DR.02): more than one differentiation rule is
  required. A single named rule uses its specific label.
- **Wendepunkt und Krümmungsverhalten** (DR.14): inflection points or explicit
  convexity, concavity, or curvature behavior.
- **Eigenschaften der Fouriertransformation** and **Eigenschaften der
  Laplacetransformation** (FT.05/LT.05): standard transform properties are used
  without proof. The transform operation itself retains FT.01/LT.01.
