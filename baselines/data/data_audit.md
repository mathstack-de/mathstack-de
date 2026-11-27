# GBERT data audit

rows: 2403 | families: 2057 (near-dup merges: 36)
splits: {'train': 1802, 'dev': 318, 'test_probability': 140, 'test_diagnostic': 60, 'excluded_near_duplicate': 83}
excluded near-duplicate groups: 199 (excluding 83 non-test relative rows from train/dev)
zero-label (valid_empty) rows: 15
train label support buckets (of 271 concepts): {'20+': 105, '5-19': 86, '1-4': 57, '0': 23}
labels/question (train): mean 3.78

information-boundary scan: CLEAN (no tans/PRT/qv/meta markers in any input)
