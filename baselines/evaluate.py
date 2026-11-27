#!/usr/bin/env python3
"""Evaluate saved probabilities: dev-selected global threshold, headline +
diagnostic tables, design-weighted + unweighted metrics, and a source_bank_category-stratified
near-duplicate-group bootstrap. Pure local computation from artifacts; no training."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PRED = HERE / "predictions"
RESULTS = HERE / "results"
BOOTSTRAP_N = 10_000
SEED = 20260717


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def label_space():
    return json.loads((DATA / "label_space.json").read_text())["concept_ids"]


def load_table():
    return pd.read_csv(DATA / "concept_tagging.csv", keep_default_na=False)


def label_matrix(rows, column, ids):
    index = {c: i for i, c in enumerate(ids)}
    y = np.zeros((len(rows), len(ids)), dtype=np.int8)
    for r, labels in enumerate(rows):
        for c in labels.split("|"):
            if c:
                y[r, index[c]] = 1
    _ = column
    return y


def micro_prf(y_true, y_pred, weights=None):
    w = np.ones(len(y_true)) if weights is None else np.asarray(weights, float)
    tp = float((w[:, None] * ((y_true == 1) & (y_pred == 1))).sum())
    fp = float((w[:, None] * ((y_true == 0) & (y_pred == 1))).sum())
    fn = float((w[:, None] * ((y_true == 1) & (y_pred == 0))).sum())
    p = tp / max(tp + fp, 1e-12)
    r = tp / max(tp + fn, 1e-12)
    return p, r, 2 * p * r / max(p + r, 1e-12)


def example_scores(y_true, y_pred, weights=None):
    w = np.ones(len(y_true)) if weights is None else np.asarray(weights, float)
    jac, exf1, exact = [], [], []
    for t, p in zip(y_true, y_pred):
        ts, ps = set(np.where(t == 1)[0]), set(np.where(p == 1)[0])
        if not ts and not ps:
            jac.append(1.0); exf1.append(1.0); exact.append(1.0)
            continue
        inter = len(ts & ps)
        jac.append(inter / max(len(ts | ps), 1))
        exf1.append(2 * inter / max(len(ts) + len(ps), 1))
        exact.append(1.0 if ts == ps else 0.0)
    jac, exf1, exact = (np.average(np.array(v), weights=w) for v in (jac, exf1, exact))
    return float(jac), float(exf1), float(exact)


def select_threshold(y_dev, prob_dev):
    best_t, best_f1 = 0.5, -1.0
    for t in np.arange(0.05, 0.96, 0.01):
        _, _, f1 = micro_prf(y_dev, (prob_dev >= t).astype(np.int8))
        if f1 > best_f1:
            best_t, best_f1 = round(float(t), 2), f1
    return best_t, best_f1


def stratified_family_resamples(near_duplicate_groups, topics, n=BOOTSTRAP_N):
    """Yield frozen source_bank_category-stratified near-duplicate-group bootstrap row indices."""
    rng = np.random.default_rng(SEED)
    near_duplicate_groups = np.asarray(near_duplicate_groups)
    topics = np.asarray(topics)
    by_topic = {}
    for source_bank_category in sorted(set(topics)):
        topic_idx = np.where(topics == source_bank_category)[0]
        fams = sorted(set(near_duplicate_groups[topic_idx]))
        by_topic[source_bank_category] = {
            fam: topic_idx[near_duplicate_groups[topic_idx] == fam] for fam in fams
        }
    for _ in range(n):
        sampled = []
        for source_bank_category in sorted(by_topic):
            idx_of = by_topic[source_bank_category]
            fams = sorted(idx_of)
            if len(fams) == 1:
                pick = fams
            else:
                pick = rng.choice(fams, size=len(fams), replace=True)
            sampled.extend(idx_of[f] for f in pick)
        yield np.concatenate(sampled)


def bootstrap_ci(y_true, y_pred, near_duplicate_groups, topics, weights, n=BOOTSTRAP_N):
    """Stratified near-duplicate-group bootstrap for the expert sample.

    source_bank_category strata follow the frozen sample design. Families are sampled within
    each stratum so the one two-row near-duplicate group remains intact. Singleton
    strata are fixed, matching the expert-reference analysis.
    """
    stats = []
    for idx in stratified_family_resamples(near_duplicate_groups, topics, n):
        stats.append(micro_prf(y_true[idx], y_pred[idx],
                               None if weights is None else np.asarray(weights)[idx])[2])
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


def eval_system(name, table, ids):
    prob_dev = np.load(PRED / f"{name}_dev.npy")
    dev = table[table["split"] == "dev"].reset_index(drop=True)
    y_dev = label_matrix(dev["labels_model_generated"], "model_generated", ids)
    threshold, dev_f1 = select_threshold(y_dev, prob_dev)
    out = {"system": name, "threshold": threshold, "dev_micro_f1": round(dev_f1, 4)}
    for split, weighted in (("test_probability", True), ("test_diagnostic", False)):
        sub = table[table["split"] == split].reset_index(drop=True)
        y = label_matrix(sub["labels_expert"], "expert", ids)
        prob = np.load(PRED / f"{name}_{split}.npy")
        pred = (prob >= threshold).astype(np.int8)
        for tag, w in ((("dw", sub["design_weight"].astype(float).to_numpy())
                        if weighted else ("uw", None)),
                       ("uw", None)):
            p, r, f1 = micro_prf(y, pred, w)
            jac, exf1, exact = example_scores(y, pred, w)
            key = f"{split}_{tag}"
            if key in out:
                continue
            out[key] = {"precision": round(p, 4), "recall": round(r, 4),
                        "micro_f1": round(f1, 4), "jaccard": round(jac, 4),
                        "example_f1": round(exf1, 4), "exact": round(exact, 4)}
        fams = sub["near_duplicate_group_id"].tolist()
        topics = sub["source_bank_category"].tolist()
        w = sub["design_weight"].astype(float).to_numpy() if weighted else None
        out[f"{split}_f1_ci95"] = bootstrap_ci(y, pred, fams, topics, w)
        # 0.5 sensitivity
        p05 = (prob >= 0.5).astype(np.int8)
        out[f"{split}_f1_at_0.5"] = round(micro_prf(y, p05, w)[2], 4)
    return out


def support_breakdown(name, table, ids, threshold):
    train = table[table["split"] == "train"]
    support = np.asarray(label_matrix(train["labels_model_generated"], "model_generated", ids).sum(0)).ravel()
    sub = table[table["split"] == "test_probability"].reset_index(drop=True)
    y = label_matrix(sub["labels_expert"], "expert", ids)
    pred = (np.load(PRED / f"{name}_test_probability.npy") >= threshold).astype(np.int8)
    rows = []
    for lo, hi, label in ((0, 0, "0"), (1, 4, "1-4"), (5, 19, "5-19"), (20, 10 ** 9, "20+")):
        cols = np.where((support >= lo) & (support <= hi))[0]
        if not len(cols):
            continue
        p, r, f1 = micro_prf(y[:, cols], pred[:, cols])
        rows.append({"bucket": label, "n_concepts": int(len(cols)),
                     "precision": round(p, 4), "recall": round(r, 4),
                     "micro_f1": round(f1, 4)})
    return rows


def topic_breakdown(name, table, ids, threshold, split):
    sub = table[table["split"] == split].reset_index(drop=True)
    y = label_matrix(sub["labels_expert"], "expert", ids)
    pred = (
        np.load(PRED / f"{name}_{split}.npy") >= threshold
    ).astype(np.int8)
    rows = []
    for source_bank_category in sorted(sub["source_bank_category"].unique()):
        idx = np.where(sub["source_bank_category"].to_numpy() == source_bank_category)[0]
        weights = (
            sub.iloc[idx]["design_weight"].astype(float).to_numpy()
            if split == "test_probability" else None
        )
        p, r, f1 = micro_prf(y[idx], pred[idx], weights)
        rows.append({
            "system": name,
            "split": split,
            "source_bank_category": source_bank_category,
            "n_questions": int(len(idx)),
            "precision": round(p, 4),
            "recall": round(r, 4),
            "micro_f1": round(f1, 4),
        })
    return rows


def paired_f1_comparison(table, ids, results, left="gbert", right="tfidf"):
    """Compare two systems on identical probability-sample bootstrap resamples."""
    sub = table[table["split"] == "test_probability"].reset_index(drop=True)
    y = label_matrix(sub["labels_expert"], "expert", ids)
    predictions = {}
    for name in (left, right):
        probability = np.load(PRED / f"{name}_test_probability.npy")
        predictions[name] = (
            probability >= results[name]["threshold"]
        ).astype(np.int8)
    weights = sub["design_weight"].astype(float).to_numpy()

    def difference(idx=None):
        if idx is None:
            idx = np.arange(len(sub))
        left_f1 = micro_prf(y[idx], predictions[left][idx], weights[idx])[2]
        right_f1 = micro_prf(y[idx], predictions[right][idx], weights[idx])[2]
        return left_f1 - right_f1

    bootstrap = [
        difference(idx)
        for idx in stratified_family_resamples(
            sub["near_duplicate_group_id"].tolist(), sub["source_bank_category"].tolist()
        )
    ]
    lo, hi = np.percentile(bootstrap, [2.5, 97.5])
    return {
        "contrast": f"{left}_minus_{right}",
        "estimand": "design_weighted_micro_f1_difference",
        "split": "test_probability",
        "point_difference": round(float(difference()), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "bootstrap_replicates": BOOTSTRAP_N,
        "seed": SEED,
        "scheme": (
            "paired source_bank_category-stratified near-duplicate-group percentile bootstrap; "
            "singleton source_bank_category strata fixed"
        ),
    }


def write_evaluation_manifest(systems):
    prediction_paths = sorted(PRED.glob("*_dev.npy"))
    for split in ("test_probability", "test_diagnostic"):
        prediction_paths.extend(sorted(PRED.glob(f"*_{split}.npy")))
    checkpoint_paths = sorted(
        path for path in (HERE / "checkpoint").glob("*") if path.is_file()
    )
    manifest = {
        "created_by": "baselines/evaluate.py",
        "systems": systems,
        "bootstrap": {
            "replicates": BOOTSTRAP_N,
            "seed": SEED,
            "scheme": (
                "source_bank_category-stratified near-duplicate-group percentile bootstrap; "
                "singleton source_bank_category strata fixed"
            ),
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn")
        },
        "sha256": {
            "modeling_table": sha256(DATA / "concept_tagging.csv"),
            "label_space": sha256(DATA / "label_space.json"),
            "split_manifest": sha256(HERE / "splits/split_manifest.json"),
            "evaluation_script": sha256(Path(__file__)),
            "gbert_run_manifest": sha256(PRED / "gbert_run_manifest.json"),
            "paired_comparisons": sha256(RESULTS / "paired_comparisons.json"),
            "predictions": {
                path.name: sha256(path) for path in prediction_paths
            },
            "checkpoint": {
                path.name: sha256(path) for path in checkpoint_paths
            },
        },
        "checkpoint_note": (
            "The base model was fetched at a pinned Hub revision "
            "(recorded in gbert_run_manifest.json). The fine-tuned checkpoint "
            "is not included; its file hashes are listed here."
        ),
    }
    (RESULTS / "evaluation_manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n"
    )


def main():
    RESULTS.mkdir(exist_ok=True)
    ids = label_space()
    table = load_table()
    systems = [p.name.replace("_dev.npy", "") for p in sorted(PRED.glob("*_dev.npy"))]
    results = {}
    topic_rows = []
    for name in systems:
        results[name] = eval_system(name, table, ids)
        results[name]["support_breakdown"] = support_breakdown(
            name, table, ids, results[name]["threshold"])
        for split in ("test_probability", "test_diagnostic"):
            topic_rows.extend(topic_breakdown(
                name, table, ids, results[name]["threshold"], split
            ))
        print(f"{name}: thr={results[name]['threshold']} "
              f"dev={results[name]['dev_micro_f1']} "
              f"prob_dw={results[name]['test_probability_dw']['micro_f1']} "
              f"CI{results[name]['test_probability_f1_ci95']} "
              f"diag={results[name]['test_diagnostic_uw']['micro_f1']}")
    (RESULTS / "metrics.json").write_text(json.dumps(results, indent=1))
    pd.DataFrame(topic_rows).to_csv(RESULTS / "per_source_bank_category.csv", index=False)
    paired = paired_f1_comparison(table, ids, results)
    (RESULTS / "paired_comparisons.json").write_text(
        json.dumps(paired, indent=1) + "\n"
    )
    write_evaluation_manifest(systems)

    lines = ["# GBERT baseline results", "",
             "Reference rows on the same expert probability sample:",
             "- v1.1 Sonnet model_generated, augmented condition (saw solutions): "
             "micro-F1 0.658 dw",
             "  (policy-compatibility re-score; generation-time prompt used different "
             "LA.11/LA.20 scope wording)",
             "- v1.1 Sonnet model_generated, no-GF prior condition: micro-F1 0.644 dw", "",
             "| system | thr | dev F1 | prob dw F1 [CI] | prob uw F1 | diag F1 |",
             "|---|---|---|---|---|---|"]
    for name, r in results.items():
        lines.append(
            f"| {name} | {r['threshold']} | {r['dev_micro_f1']} | "
            f"{r['test_probability_dw']['micro_f1']} {r['test_probability_f1_ci95']} | "
            f"{r['test_probability_uw']['micro_f1']} | "
            f"{r['test_diagnostic_uw']['micro_f1']} |")
    support_by_system = {
        name: {row["bucket"]: row for row in results[name]["support_breakdown"]}
        for name in ("tfidf", "gbert")
    }
    lines.extend([
        "",
        "Paired GBERT - TF-IDF comparison on the probability sample: "
        f"{paired['point_difference']:+.4f} micro-F1 "
        f"(95% CI {paired['ci95']}). The interval uses identical resamples "
        "for both systems.",
        "",
        "| model_generated train positives | concepts | TF-IDF F1 | GBERT F1 |",
        "|---|---:|---:|---:|",
    ])
    for bucket in ("0", "1-4", "5-19", "20+"):
        tfidf_row = support_by_system["tfidf"][bucket]
        gbert_row = support_by_system["gbert"][bucket]
        lines.append(
            f"| {bucket} | {tfidf_row['n_concepts']} | "
            f"{tfidf_row['micro_f1']:.4f} | "
            f"{gbert_row['micro_f1']:.4f} |"
        )
    run_manifest = json.loads((PRED / "gbert_run_manifest.json").read_text())
    best_epoch = run_manifest.get("best_epoch")
    epochs_run = run_manifest.get("epochs_run")
    lines.extend([
        "",
        "The support table is an unweighted diagnostic on the 140-item "
        "probability sample; buckets use positive model_generated training examples.",
        "",
        "Intervals use 10,000 source_bank_category-stratified near-duplicate-group bootstrap "
        "replicates; singleton source_bank_category strata are fixed. GBERT is the model_generated-dev "
        f"checkpoint selected by early stopping at epoch {best_epoch} "
        f"(150-epoch cap, patience 10; early stopping reached at epoch "
        f"{epochs_run}). Late-epoch training loss was unstable; the retained "
        "checkpoint is the early-stopping selection and is unaffected.",
    ])
    (RESULTS / "RESULTS.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
