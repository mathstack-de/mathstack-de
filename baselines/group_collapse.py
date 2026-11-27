#!/usr/bin/env python3
"""Thematic-group collapse (22 groups) of the frozen test-probability
predictions, reusing each system's archived dev-selected fine-grained
threshold. Pure local computation from artifacts; no training."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive_115epoch_20260726"
DATA = HERE / "data"


def main():
    ids = json.loads((DATA / "label_space.json").read_text())["concept_ids"]
    table = pd.read_csv(DATA / "concept_tagging.csv", keep_default_na=False)
    metrics = json.loads((ARCHIVE / "results/metrics.json").read_text())
    idx = {c: i for i, c in enumerate(ids)}
    groups = sorted({c.split(".")[0] for c in ids})
    gmap = np.zeros((len(ids), len(groups)), dtype=np.int8)
    for c, i in idx.items():
        gmap[i, groups.index(c.split(".")[0])] = 1

    test = table[table.split == "test_probability"].reset_index(drop=True)
    weights = test.design_weight.astype(float).to_numpy()

    def label_mat(column):
        y = np.zeros((len(test), len(ids)), dtype=np.int8)
        for r, labels in enumerate(test[column]):
            for c in labels.split("|"):
                if c:
                    y[r, idx[c]] = 1
        return y

    def collapse(y):
        return (y @ gmap > 0).astype(np.int8)

    def micro_prf(y_true, y_pred):
        w = weights[:, None]
        tp = float((w * ((y_true == 1) & (y_pred == 1))).sum())
        fp = float((w * ((y_true == 0) & (y_pred == 1))).sum())
        fn = float((w * ((y_true == 1) & (y_pred == 0))).sum())
        p = tp / max(tp + fp, 1e-12)
        r = tp / max(tp + fn, 1e-12)
        return p, r, 2 * p * r / max(p + r, 1e-12)

    y_true = collapse(label_mat("labels_expert"))
    out = {"n_groups": len(groups), "weights": "design_weight (design)",
           "note": "thresholds reused from fine-grained dev selection, "
                   "not re-tuned at group level"}
    p, r, f = micro_prf(y_true, collapse(label_mat("labels_model_generated")))
    out["sonnet"] = {"precision": round(p, 4), "recall": round(r, 4),
                     "micro_f1": round(f, 4)}
    for name in ("gbert", "tfidf"):
        th = metrics[name]["threshold"]
        prob = np.load(HERE / f"predictions/{name}_test_probability.npy")
        p, r, f = micro_prf(y_true, collapse((prob >= th).astype(np.int8)))
        out[name] = {"threshold": th, "precision": round(p, 4),
                     "recall": round(r, 4), "micro_f1": round(f, 4)}
    (HERE / "results/group_collapse_metrics.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
