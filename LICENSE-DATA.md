# Licence of the experiment records: CC BY-SA 4.0

Many files in this repository are records, not code: sampled questions and
their rendered instances, prompts, model outputs, worked solutions, labels,
predictions and metrics. Where such a file contains question content or
content derived from it, it is licensed under the **Creative Commons
Attribution-ShareAlike 4.0 International** licence (CC BY-SA 4.0,
https://creativecommons.org/licenses/by-sa/4.0/), like the dataset. Some
of the questions descend from a collection of 166 STACK questions for the courses Höhere Mathematik 1 and 2 of the project SKATING at Hochschule Karlsruhe - Technik und Wirtschaft (Karlsruhe University of Applied Sciences), cited here as "STACK questions for Höhere Mathematik 1 and 2" (below: the Karlsruhe collection). As in the
dataset, the text of the 21 of them that are not treated
as adaptations of their collection question (11
taken over unchanged from the Karlsruhe collection,
10 changed only in the typesetting of formulas or
in penalty settings) keeps CC BY-SA 3.0 DE (below).

Attribute as described in the dataset release (https://huggingface.co/datasets/mathstack-de/MathStack-DE): cite the
dataset and the paper and name "MathStack-DE 1.0.0, compiled by Lucy
Weggler and
prepared for release by Fahad Deshmukh from the work of the credited
authors, CC BY-SA 4.0". The dataset's
`AUTHORS.md` gives the credit of each question and worked solution and names
the contributors of the course banks. The credits of questions give the
institution as CIH HTW Berlin. CIH is the Curriculum Innovation Hub of HTW Berlin (https://www.htw-berlin.de/lehre/lehrinnovation/curriculum-innovation-hub/). The questions and
worked solutions remain the work of their authors. Some of the questions come from the *Digitaler Aufgabenpool
Mathematik* of Technische Hochschule Köln by Heiko Knospe, Jan-Philipp
Schmidt, Angela Schmitz, Patricia Maria Graf, Jan Siegfried Reißner and
Andreas Schwenk (CC BY-SA 4.0, https://aufgabenpool.th-koeln.de/pool.php).
The records reproduce question texts in the form the models received them,
apart from the changes listed in `README.md` (Notes on the records).

22 of the questions are adapted from Google's *Machine Learning
Crash Course* (https://developers.google.com/machine-learning/crash-course/),
whose content Google licenses, except where otherwise noted, under CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/). Portions of these questions
are modifications based on work created and shared by Google and used
according to terms described in the Creative Commons 4.0 Attribution
License. They were translated into German or adapted from Google's German
translation of the page, and changed. `ADAPTED_SOURCES.json`, a copy of the
dataset's `manifests/adapted_sources.json`, lists these questions by their
identifier (`rc_id`; the column is called `question_id` in
`baselines/data/concept_tagging.csv`) with the page of the course each one
comes from and archived copies of that page. The records that reproduce
their text (`baselines/data/concept_tagging.csv`, `labeling/corpus_run/prompts_and_responses.csv.gz`) have no credit column, so the credit
is given here. The material taken from the course remains under CC BY 4.0.
Naming Google as the source does not imply that Google endorses, sponsors or
is otherwise connected with this repository.

8 of the questions take text from pages of the German Wikipedia
(https://de.wikipedia.org/) and the German Wikibooks
(https://de.wikibooks.org/). In the dataset the credit of each names its
page, the version of the page that it cites, the licence and that the
question was changed; `ADAPTED_SOURCES.json` (`wiki_pages`) lists them by
their identifier with the page and the version. The records that reproduce
their text (`baselines/data/concept_tagging.csv`, `labeling/corpus_run/prompts_and_responses.csv.gz`) have no credit column, so the credit is
given here; they hold the text as the runs received it. The German
Wikipedia states CC BY-SA 4.0
(https://creativecommons.org/licenses/by-sa/4.0/) for its text. The page of
the Wikibooks book "Mathe für Nicht-Freaks" states CC BY-SA 3.0
(https://creativecommons.org/licenses/by-sa/3.0/) in its own notice and
asks that the book be named as the source (the footer of that site states
CC BY-SA 4.0). Text under CC BY-SA 3.0 may be adapted under a later version
of that licence, and these questions are released under CC BY-SA 4.0.

190 questions of the contributed banks descend from
the Karlsruhe collection, whose questions are under
CC BY-SA 3.0 DE (https://creativecommons.org/licenses/by-sa/3.0/de/); the Karlsruhe
collection is not published online. The records that reproduce their text
(`baselines/data/concept_tagging.csv`, `contract_pilot/answers.jsonl`, `contract_pilot/inputs/gated_pool.jsonl`, `contract_pilot/instances.jsonl`, `generation/answer_blind_generation/additional_attempt_1/prompt_plan.jsonl`, `generation/answer_blind_generation/additional_attempt_2/prompt_plan.jsonl`, `generation/answer_blind_generation/prompt_plan.jsonl`, `labeling/corpus_run/prompts_and_responses.csv.gz`, `variant_study/answers.jsonl`, `variant_study/instances.jsonl`) have no credit column, so the credit is given
here. We treat a question as an adaptation of its collection question when it differs from it in wording, question variables, inputs or the logic of a response tree (169 questions). An adaptation is released under CC BY-SA 4.0, which section 4b of CC BY-SA 3.0 DE allows; the material taken from the Karlsruhe collection remains under CC BY-SA 3.0 DE. A question that equals its collection question in every field (11), or differs from it only in the typesetting of formulas or in penalty settings (10), is not treated as an adaptation and keeps CC BY-SA 3.0 DE. The 21 questions that
keep CC BY-SA 3.0 DE keep it in these records as well; the
dataset's `LICENSE-DATA.md` says when a question counts as taken over
unchanged or as changed in typesetting or penalty settings only.
36 questions of the Technische Hochschule Köln pool
descend from the Karlsruhe collection as well. They keep the credit and
licence of the pool, because the pool publishes them under its own licence
and names no source; in the dataset their credit also names their
collection question, because they descend from it.
8 questions of the Karlsruhe collection are German
versions of questions of the STACK question library (https://github.com/maths/moodle-qtype_stack/tree/master/samplequestions/stacklibrary), from
STACK Library - Algebra Refresher (Tony Barnard) and STACK Library - Calculus Refresher (Tony Croft and Anthony Kay), which the STACK project publishes under
CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/; statement:
https://docs.stack-assessment.org/en/About/License/). 7 of the
190 and 4 questions of the
Technische Hochschule Köln pool descend from them; the material that they
take from the library remains under
CC BY-SA 4.0. One of the 7 questions of the contributed banks that descend from them was changed in typesetting or penalty settings only and keeps CC BY-SA 3.0 DE; its credit names both licences.
`KARLSRUHE_COLLECTION.json`, a copy of the dataset's
`manifests/karlsruhe_collection.json`, lists these questions by their
identifier (`rc_id`) with their collection question, whether and how they
were changed, their credit and their licence; for each one whose collection
question is a German version of a question of the library it names that
question with its part, its authors and its file, and it names the licence
of the library. Naming the source does not imply that Hochschule Karlsruhe - Technik und Wirtschaft or the project SKATING endorse, sponsor or are otherwise connected with this repository.

Source code is licensed under the MIT licence (`LICENSE`).
