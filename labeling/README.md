# Concept labeling records

## `corpus_run/`: the run that produced the released labels

Claude Sonnet 4.6 labeled all 2,403 questions at temperature zero. The
`annotations` table of the dataset holds its output.

- `labeling_prompt.txt`: the instruction text of the run (SHA-256
  `7f018d8f44ba57828b35ed4df5721182abde6bc3dcbbafaa3d8b8203c43328da`, the value recorded in the dataset's
  `manifests/annotation_run_manifest.json`). The 271 vocabulary entries were
  supplied through a closed-label tool.
- `prompts_and_responses.csv.gz`: for every question, the final prompt and
  the raw response. `prompt_sha256` is the hash of the prompt as it was sent.
  The prompts of three questions whose text was replaced
  (`rc-70e21739-b124-4f9f-bce7-e20dc49a952d`,
  `rc-29cd2759-a17b-4572-89b8-7eecac4507b9` and
  `rc-23e8a8fa-2299-4d73-9dc2-96fc9bf89938`) are replaced by a note; the
  prompts of the other questions that the dataset's
  `manifests/question_content_replacements.json` lists keep the text the run
  received. In the prompt of one question a working note of its author is
  removed, as in the dataset; the responses are the ones the run returned.
- `generated_solution_context.jsonl`: the 255 questions whose prompt carried
  a generated worked solution, with the generation mode of each (12 came from
  the answer-conditioned repair stage) and whether the solution is in the
  dataset (252 are; an expert rejected one and left two unconfirmed).
- `model_generated_labels_full_corpus.csv`: the normalized labels (the
  remarks of a question author at the end of six question names are removed,
  as in the dataset, so the file differs from the one the run wrote).
- `expert_reference_agreement_metrics.json`: agreement with the expert
  reference (Section 5.2 of the paper). It was computed against the
  released expert reference, the `expert_reference` table of the dataset,
  and can be recomputed from that table and the labels above.
- `run_manifest.json`: the run's own record of inputs, outputs and counts.

## `policy_compatibility_sensitivity.json`: the two checks of Appendix H

- `definition_scope_rerun`: the result of the 200-question sensitivity run
  with the two released scopes (66.4% design-weighted micro-F1 on the
  probability sample; +0.6 points against the corpus-run labels). The
  labels of that run are not included here; the record names its inputs
  by hash.
- `expert_reference_version_sensitivity`: the agreement of the corpus-run
  labels without the four probability-sample questions whose labels differ
  between the archived evaluation labels and the released expert reference
  (`rc-01963e1d-49eb-4c24-a42f-679b65ec7514`,
  `rc-4194d019-7fa8-4c74-96f3-5b229f368362`,
  `rc-53605a00-5eb2-4e1a-970c-9e3907fd4841`,
  `rc-a8091fa4-a0cc-425e-9590-4aa148fb516b`; a fifth such question,
  `rc-fa25c9e6-d2b4-4938-8b25-c6c2f3ccfcfb`, is in the diagnostic sample).

## Other files

- `input_manifest.json`, `stack_controls.jsonl`, `cloze_sanitization.jsonl`:
  the record of how question text was prepared before labeling (rendering at
  seed 42, visible options of selection inputs, removal of correctness
  markers from cloze questions). `input_manifest.json` describes the base
  model input; its `sha256.system_prompt_v1_1` entry is the prompt of the
  earlier 200-question run that `ERRATA.md` names, not the prompt of the
  corpus run. The corpus run used the prompt in
  `corpus_run/labeling_prompt.txt` and a model input to which the generated
  worked solutions had been added; `corpus_run/run_manifest.json` identifies
  that input (`sha256.input_manifest`, `sha256.model_input_xml`). The
  model-input XML files themselves are not included; the final prompts are in
  `corpus_run/`.
