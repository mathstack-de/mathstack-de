# MathStack-DE: code and experiment records

Version 1.0.0. This repository accompanies the paper *MathStack-DE: A
Natural-Language and Symbolic Mathematics Corpus with Executable Grading*
(Findings of EACL 2027). It holds the code and the frozen records behind the
numbers in the paper. The dataset itself is published separately:

- Dataset: https://huggingface.co/datasets/mathstack-de/MathStack-DE
- Dataset DOI: https://doi.org/10.57967/hf/11896
- This repository: https://github.com/mathstack-de/mathstack-de

## What is here

| Folder | Content | Paper |
| --- | --- | --- |
| `variant_study/` | The randomized-instance study: frozen protocol and draw, the 60 questions with four instances each, prompts, raw model outputs, STACK verdicts, analysis code, bootstrap outputs, and the 170 archived responses at source-course seeds | Section 6, Appendix F |
| `variant_study/sensitivity/outer_brace_regrade/` | A separate regrade that unwraps redundant outer braces. The paper uses it only for the named sensitivity analysis in Appendix F (nine changed scores; 192 and 187 of 240 full-credit responses); see `ERRATA.md` | Appendix F, Appendix K |
| `variant_study/sensitivity/answer_extraction/` | Post-hoc recovery of answers from GLM-Z1 format failures under three fixed rules. Its counts cover all 32 format failures, including the one archived anchor response; Table 14 gives the 31 in the scope of the paper | Section 6.2, Table 14 |
| `contract_pilot/` | The post-hoc pilot on 20 questions with non-`AlgEquiv` tests: frozen protocol, selection, instances, raw outputs, verdicts, analysis | Section 6.2, Appendix I |
| `grading_contract_audit/` | Structural features of every Potential Response Tree in the corpus and the script that computes them | Section 4.1, Figure 2 |
| `known_verdict/` | The known-verdict suite (39 pairs with a fixed verdict and five unscored probes) and its results | Section 4.2, Appendix E |
| `render_audit/` | The five-seed render audit of all 1,604 STACK questions | Section 4.2 |
| `generation/` | Worked-solution generation: system prompts, the prompt of every question, raw outputs and run records, for the answer-blind run and the answer-conditioned repair | Section 4.3, Appendix G |
| `labeling/` | Concept labeling: the prompt of the corpus-scale run, the final prompt and raw response of every question, the labels and the agreement metrics | Section 5, Appendix H |
| `baselines/` | Supervised baselines: training and evaluation code, inputs, near-duplicate-separated splits, saved probabilities and metrics | Section 5.3, Appendix H |
| `builders/` | The scripts that build and validate the corpus tables | Section 3 |
| `vocabulary/` | The 271-label vocabulary and the labeling policy (identical to the dataset release) | Section 5.1 |
| `manifests/evaluation_sets.json` | Sizes, identifier hashes and pairwise overlaps of the STACK question sets of Appendix B (key names below) | Appendix B |

The folders have a README or protocol file; `manifests/` and `vocabulary/`
are described in the table above. `SHA256SUMS.json` lists the hash of every
other file, and `ERRATA.md` documents a correction of the files that the
reviewers of the paper received.

`manifests/evaluation_sets.json` names the sets of Appendix B as follows:
`stack_questions` (1,604) and `labeling_population` (1,574), each with its
size and a hash of its identifiers; `labeling_step_count_development_exclusion`
(the labeling exclusion, 30); `expert_reference` (200);
`randomized_study_development` (40) and `worked_solution_development_union`
(35, with its two parts), which together are the 75 randomized-evaluation
exclusions; `randomized_study_sample` (the randomized evaluation, 60); and
`replicate_subset` (the replicate comparison, 12). The identifiers of every
set other than the first two are listed under `pairwise_intersections`, in
the entry that pairs the set with `stack_questions`. The training and
development split is in `baselines/splits/`, and the 20 pilot questions are
in `contract_pilot/selection.csv`.

## What you can run

These run from this repository with Python 3.12 and the packages in
`requirements.txt` (`pip install -r requirements.txt`):

- **The tests** in `variant_study/` and `grading_contract_audit/`:
  `python -m pytest variant_study grading_contract_audit`.
- **The paper's numbers for the randomized-instance study**:
  `cd variant_study && python recompute_paper_numbers.py` applies the scope
  of the paper (1,440 of the 1,610 recorded responses) and recomputes the
  counts of Section 6.2, Figure 3 and Tables 10, 11 and 13 from
  `results.csv`, the contract features and the outer-brace regrade. It
  compares them with `paper_scope_summary.json` and
  `outcome_decomposition.json` and ends with an error if a value differs.
- **The prespecified analysis of the complete grid**:
  `cd variant_study && python analyze.py` checks `results.csv` against
  `grade_manifest.json` and rewrites `analysis.json` with the same content.
  The paper takes the bootstrap intervals of the full-credit rates and the
  comparison of repeated prompts from it (Figure 3, Tables 10 and 12). Its
  checker totals cover all 1,610 responses, including the 170 archived
  responses at source-course seeds that the paper excludes, so they differ
  from Table 13 (1,532 responses with full or zero credit, where the scope
  of the paper has 1,366).
- **The pilot counts**: `cd contract_pilot && python analyze_pilot.py`;
  `python reproductions/recount_20260916.py` recounts them for the three
  comparison methods and the partial-credit responses, and
  `python select_pilot.py --dry-run` repeats the seeded draw from the
  shipped pool and prints the 20 questions of `selection.csv`.
- **The known-verdict suite**: `cd known_verdict && python rescore.py
  results.csv` writes `results_rescored_summary.json` with the content of
  `rescored_summary.json`; `run_suite.py` needs a GoeMaxima service
  (`known_verdict/README.md`).
- **The baseline metrics** from the saved probabilities:
  `cd baselines && python evaluate_encoders.py` rewrites the ModernGBERT
  metrics with the same content. `python evaluate.py` recomputes the
  frequency, TF-IDF and GBERT metrics (the same values as the shipped
  entries) and adds the ModernGBERT systems; it overwrites
  `results/metrics.json`, `results/per_source_bank_category.csv`,
  `results/RESULTS.md` and `results/evaluation_manifest.json` (whose shipped
  version also records hashes of the omitted GBERT checkpoint), so run it on
  a copy (`results/paired_comparisons.json` is rewritten with the same
  content). scikit-learn is needed only to record its version; without it
  the script stops at the end, after it has rewritten the first two files.

Grading a response needs the two pinned containers (STACK API and
GoeMaxima); the dataset's `GRADING.md` gives the image digests and runnable
examples.

The other scripts document how the records were produced. They read files
that are not part of this repository (source exports, intermediate files,
model checkpoints) and do not run from here; their outputs are included next
to them.

## Notes on the records

- The records keep the question text that the experiments used. A few
  questions were corrected or cleaned for the release afterwards, so their
  text here can differ from the dataset, which lists them in
  `manifests/question_content_replacements.json` and
  `manifests/content_cleanup.json`.
- As in the dataset, working notes of question authors are removed and the
  names of the source banks are given as codes.
- Some files were edited for publication, so hashes recorded inside the
  records, such as prompt hashes, may not match the shipped files;
  `SHA256SUMS.json` lists the shipped files.
- Commit identifiers in the run records refer to the authors' development
  code, which is not published; the source exports named in `corpus_sha256`
  are not distributed either.
- Paths that start with `not_included/` name inputs that are not part of
  this repository. The script that collected the model responses is not
  included; its prompt template is in `variant_study/prompt_template.json`.
- Request identifiers, token counts, costs, latencies and timestamps were
  removed from the response and generation records.
- The fine-tuned GBERT checkpoint is not included because of its size; its
  file hashes are in `baselines/SHA256SUMS_115epoch_archive` and
  `baselines/results/evaluation_manifest.json`. The ModernGBERT runs kept no
  checkpoint. Two training logs named in the checksum list of `baselines/`
  are not included.

## Terms used in the records

- `A0` to `A3` and `THK` are the source-bank codes of the dataset. A code
  names a bank or a category, not the author of a question; the dataset's
  `DATASHEET.md` explains the codes in category names.
- `kind` in the study files: `fresh` is a response to one of the four
  instances, `replicate` a repeated response to the same prompt, `anchor` one
  of the 170 archived responses at source-course seeds (not used for the
  paper's aggregates).
- "Arm" in the study code means one of the secondary checkers in the
  checker diagnostics, and one side (anchor or fresh) of the
  anchor-versus-fresh comparison where it says "both arms".
- `variant_study/PROTOCOL_frozen.md` is the protocol fixed before
  collection, with a status line and a closing section that record what
  changed after it was fixed; `variant_study/PROTOCOL.md` is a later summary
  of the study.
- `tans` is a STACK teacher answer.

## Licence

Code: MIT (`LICENSE`). Records that contain question content, worked
solutions or model outputs about them: CC BY-SA 4.0 (`LICENSE-DATA.md`).
22 of the questions are adapted from Google's Machine Learning
Crash Course (CC BY 4.0); `LICENSE-DATA.md` gives the credit and
`ADAPTED_SOURCES.json` the page of the course for each of them.
8 of the questions take text from pages of the German Wikipedia or
the German Wikibooks; `LICENSE-DATA.md` gives the credit and
`ADAPTED_SOURCES.json` (`wiki_pages`) the page and the version for each of
them.
190 questions of the contributed banks descend from
a collection of 166 STACK questions for the courses Höhere Mathematik 1 and 2 of the project SKATING at Hochschule Karlsruhe - Technik und Wirtschaft (Karlsruhe University of Applied Sciences), cited here as "STACK questions for Höhere Mathematik 1 and 2" (below: the Karlsruhe collection). Its questions are under
CC BY-SA 3.0 DE (https://creativecommons.org/licenses/by-sa/3.0/de/), and the
21 of the 190 that are not
treated as adaptations (11 taken over unchanged,
10 changed only in the typesetting of formulas or
in penalty settings) keep that licence. 8 questions of the
Karlsruhe collection are German versions of questions of the STACK question
library (https://github.com/maths/moodle-qtype_stack/tree/master/samplequestions/stacklibrary), from STACK Library - Algebra Refresher (Tony Barnard) and STACK Library - Calculus Refresher (Tony Croft and Anthony Kay), which the STACK project
publishes under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/);
7 of the 190 and
4 questions of the Technische Hochschule Köln pool descend
from them. `LICENSE-DATA.md` gives the credit; `KARLSRUHE_COLLECTION.json`
names the collection question of each of these questions and, where it is a
German version of a question of the library, that question with its
authors, its licence and its file.

## Citation

The dataset and the paper:

```bibtex
@misc{weggler2026mathstackde,
  title     = {{MathStack-DE}},
  author    = {Weggler, Lucy and Deshmukh, Fahad},
  year      = {2026},
  version   = {1.0.0},
  publisher = {Hugging Face},
  doi       = {10.57967/hf/11896},
  url       = {https://huggingface.co/datasets/mathstack-de/MathStack-DE}
}

@inproceedings{deshmukh2027mathstackde,
  title     = {{MathStack-DE}: A Natural-Language and Symbolic Mathematics Corpus with Executable Grading},
  author    = {Deshmukh, Fahad and Weggler, Lucy},
  booktitle = {Findings of the Association for Computational Linguistics: EACL 2027},
  year      = {2027},
  publisher = {Association for Computational Linguistics}
}
```

## Contact

fahad.deshmukh@htw-berlin.de or lucy.weggler@htw-berlin.de. Corrections and removal requests go to either address.
