# Concept-Tagging Baseline Protocol

## Task and data

The task is multilabel prediction over the fixed 271-concept vocabulary. Each
encoder receives only the rendered question text and visible answer options.
It does not receive worked solutions, Maxima programs, teacher answers, grading
logic, or expert concept labels. Training and development targets are the
released model-generated concept labels.

The near-duplicate-group-separated split contains 1,802 training questions,
318 development
questions, 140 probability-test questions, 60 diagnostic-test questions, and
83 questions excluded as near-duplicate relatives of the expert reference.
Question identifiers and near-duplicate groups do not cross from training or
development into either test set. The expert labels are absent from every
training bundle and are used only for final evaluation.

## Systems

- **Frequency:** predict the globally most frequent training labels; select the
  number of labels on development micro-F1.
- **TF-IDF:** word 1-2 grams and character 3-5 grams with class-balanced
  one-vs-rest logistic regression. Select `C` from {0.5, 1, 2} on development
  micro-F1.
- **GBERT:** `deepset/gbert-base` with a 271-dimensional sigmoid head,
  weighted binary cross-entropy, maximum length 384, batch size 16, learning
  rate 2e-5, and one fixed seed. Early stopping uses development micro-F1 at
  threshold 0.5; the retained checkpoint is epoch 105.
- **ModernGBERT:** the 134M and 1B encoders use the same data, head, loss,
  maximum length, batch size, and fixed seed. Learning rates 2e-5 and 5e-5 are
  compared for each size using development labels only. The reported 1B model
  uses 2e-5 and the checkpoint selected at epoch 14.

Each system uses one training seed. The package includes all four ModernGBERT
run manifests and predictions, including configurations not selected on the
development set.

## Thresholds and evaluation

One global threshold per system is selected on development micro-F1 and then
applied unchanged to both expert-reference samples. The 140-question
probability sample provides the design-weighted headline estimates. The
60-question diagnostic sample is unweighted and is never pooled with the
probability sample.

Confidence intervals use 10,000 source-bank-category-stratified bootstrap
samples. Trained-system resampling keeps near-duplicate groups intact. Paired
contrasts use identical resamples. Support-bucket results are unweighted
micro-F1 within each training-support bucket.

The Sonnet row is contextual rather than a directly comparable trained
baseline. Sonnet produced the training labels at temperature zero under the
documented annotation policy and could use available worked solutions; the
trained baselines receive learner-visible question content only.

## Included evidence

`data/`, `splits/`, `predictions/`, and `results/` contain the model inputs,
split membership, probabilities, run manifests, metrics, paired contrasts, and
support diagnostics. The checkpoint archives are omitted for size; their
SHA-256 inventories are included.
