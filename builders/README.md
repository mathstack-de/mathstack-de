# Corpus builders

These scripts construct and validate the corpus tables. They are included so
that the extraction, normalization, grading replay and validation logic can
be inspected.

1. `build_source.py`: extracts stable question records and the executable
   STACK fields from the source exports.
2. `build_vocabulary.py`: emits the 271-label vocabulary and the label maps.
3. `build_generated_solutions.py`: links generated worked solutions to their
   verification evidence.
4. `build_annotations.py`: builds the table of model-generated concept
   labels.
5. `build_expert_reference.py`: builds the expert reference and the
   near-duplicate-separated splits.
6. `build_solving.py`: renders one instance of every automatically gradable
   STACK question and produces the two solving tables.
7. `validate_release.py` and `test_build.py`: enforce table, leakage,
   provenance and grading invariants.

`requirements.txt` lists the Python packages. The scripts read the source
exports and intermediate files (paths under `not_included/`), which are not
part of this repository, so they do not run from here. Source banks are named
by the codes of the dataset; `author_credits.py` holds the credit of each
bank code as the corpus tables carry it, and the dataset's `AUTHORS.md` gives
the credit of every question. Some questions descend from
a collection of 166 STACK questions for the courses Höhere Mathematik 1 and 2 of the project SKATING at Hochschule Karlsruhe - Technik und Wirtschaft (Karlsruhe University of Applied Sciences), cited here as "STACK questions for Höhere Mathematik 1 and 2" (below: the Karlsruhe collection); they are credited to it in the dataset.
