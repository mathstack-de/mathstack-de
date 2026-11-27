# GBERT baseline results

Reference rows on the same expert probability sample:
- v1.1 Sonnet model-generated, augmented condition (saw solutions): micro-F1 0.658 dw
  (policy-compatibility re-score; generation-time prompt used different LA.11/LA.20 scope wording)
- v1.1 Sonnet model-generated, no-GF prior condition: micro-F1 0.644 dw

| system | thr | dev F1 | prob dw F1 [CI] | prob uw F1 | diag F1 |
|---|---|---|---|---|---|
| frequency | 0.05 | 0.1135 | 0.0879 (0.0758, 0.1003) | 0.0862 | 0.0697 |
| gbert | 0.67 | 0.5976 | 0.5 (0.4659, 0.5345) | 0.4963 | 0.3896 |
| tfidf | 0.54 | 0.5749 | 0.4744 (0.4414, 0.5071) | 0.4743 | 0.4076 |

Paired GBERT - TF-IDF comparison on the probability sample: +0.0256 micro-F1 (95% CI [0.0005, 0.0512]). The interval uses identical resamples for both systems.

| model-generated train positives | concepts | TF-IDF F1 | GBERT F1 |
|---|---:|---:|---:|
| 0 | 23 | 0.0000 | 0.0000 |
| 1-4 | 57 | 0.3636 | 0.2759 |
| 5-19 | 86 | 0.4065 | 0.4386 |
| 20+ | 105 | 0.4897 | 0.5143 |

The support table is an unweighted diagnostic on the 140-item probability sample; buckets use positive model-generated training examples.

Intervals use 10,000 source-bank category-stratified near-duplicate-group bootstrap replicates; singleton source-bank category strata are fixed. GBERT is the model-generated-dev checkpoint selected by early stopping at epoch 105 (150-epoch cap, patience 10; early stopping reached at epoch 115). Late-epoch training loss was unstable; the retained checkpoint is the early-stopping selection and is unaffected.
