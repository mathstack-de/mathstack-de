#!/usr/bin/env python3
"""Score the ModernGBERT sweep with the frozen concept-tagging protocol.

Reuses evaluate.py verbatim for every scoring decision: the decision
threshold is selected on the model_generated development set, expert-reference scores
are design-weighted on the 140-question probability sample, and intervals
come from the same 10,000-sample source_bank_category-stratified near-duplicate-group bootstrap.
The learning rate for each encoder is also selected on model_generated development
data, so no expert label influences any model or hyperparameter choice.

Writes results/moderngbert_metrics.json and prints a comparison table.
"""
import json
from pathlib import Path

import numpy as np

import evaluate as ev

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

SWEEP = {
    "moderngbert134m": ["moderngbert134m_lr2e5", "moderngbert134m_lr5e5"],
    "moderngbert1b": ["moderngbert1b_lr2e5", "moderngbert1b_lr5e5"],
}
REFERENCE_SYSTEMS = ("frequency", "tfidf", "gbert")


def main():
    ids = ev.label_space()
    table = ev.load_table()

    # Learning-rate selection on model_generated dev only, mirroring threshold choice.
    selected, sweep_rows = {}, []
    for family, tags in SWEEP.items():
        scored = []
        for tag in tags:
            manifest_path = ev.PRED / f"{tag}_run_manifest.json"
            if not manifest_path.is_file():
                print(f"  [skip] {tag}: run not finished")
                continue
            manifest = json.loads(manifest_path.read_text())
            dev_prob = np.load(ev.PRED / f"{tag}_dev.npy")
            dev = table[table["split"] == "dev"].reset_index(drop=True)
            y_dev = ev.label_matrix(dev["labels_model_generated"], "model_generated", ids)
            threshold, dev_f1 = ev.select_threshold(y_dev, dev_prob)
            scored.append({
                "tag": tag,
                "lr": manifest["lr"],
                "parameters": manifest["parameters"],
                "dev_micro_f1_at_selected_threshold": round(dev_f1, 4),
                "dev_f1_at_0.5": manifest["best_dev_f1_at_0.5"],
                "best_epoch": manifest["best_epoch"],
                "epochs_run": manifest["epochs_run"],
                "stop_reason": manifest["stop_reason"],
                "wall_minutes": round(manifest["wall_s"] / 60, 1),
                "selection_threshold": threshold,
            })
        if not scored:
            raise SystemExit(f"no completed runs for {family}")
        scored.sort(key=lambda r: -r["dev_micro_f1_at_selected_threshold"])
        selected[family] = scored[0]["tag"]
        sweep_rows.extend(scored)

    systems = list(REFERENCE_SYSTEMS) + [selected[f] for f in SWEEP]
    results = {name: ev.eval_system(name, table, ids) for name in systems}
    for family in SWEEP:
        name = selected[family]
        results[name]["support_breakdown"] = ev.support_breakdown(
            name, table, ids, results[name]["threshold"])

    comparisons = []
    for family in SWEEP:
        comparisons.append(
            ev.paired_f1_comparison(table, ids, results,
                                    left=selected[family], right="gbert"))
    comparisons.append(
        ev.paired_f1_comparison(table, ids, results,
                                left=selected["moderngbert1b"],
                                right="tfidf"))
    comparisons.append(
        ev.paired_f1_comparison(table, ids, results,
                                left=selected["moderngbert1b"],
                                right=selected["moderngbert134m"]))

    out = {
        "created_by": "baselines/evaluate_encoders.py",
        "protocol": (
            "frozen concept-tagging protocol: model-generated-dev threshold selection, "
            "design-weighted micro-F1 on the 140-question probability sample, "
            "10,000-sample source_bank_category-stratified near-duplicate-group bootstrap; the "
            "learning rate per encoder is selected on model-generated development data"
        ),
        "learning_rate_selection": sweep_rows,
        "selected": selected,
        "systems": results,
        "paired_comparisons": comparisons,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "moderngbert_metrics.json").write_text(
        json.dumps(out, indent=2) + "\n")

    print("\nlearning-rate selection (model_generated dev only)")
    print(f"{'tag':<24}{'lr':>8}{'params':>10}{'dev F1':>9}{'epochs':>8}"
          f"{'min':>7}")
    for row in sweep_rows:
        print(f"{row['tag']:<24}{row['lr']:>8.0e}"
              f"{row['parameters'] / 1e6:>9.0f}M"
              f"{row['dev_micro_f1_at_selected_threshold']:>9.4f}"
              f"{row['epochs_run']:>8}{row['wall_minutes']:>7.1f}")

    print("\nexpert-reference agreement (design-weighted, probability sample)")
    print(f"{'system':<24}{'P':>7}{'R':>7}{'F1':>7}  {'95% CI':<18}{'Diag':>7}")
    for name in systems:
        r = results[name]
        dw = r["test_probability_dw"]
        lo, hi = r["test_probability_f1_ci95"]
        diag = r["test_diagnostic_uw"]["micro_f1"]
        print(f"{name:<24}{dw['precision'] * 100:>7.1f}"
              f"{dw['recall'] * 100:>7.1f}{dw['micro_f1'] * 100:>7.1f}  "
              f"[{lo * 100:.1f}, {hi * 100:.1f}]".ljust(20)
              + f"{diag * 100:>6.1f}")

    print("\npaired contrasts (same bootstrap resamples)")
    for comparison in comparisons:
        lo, hi = comparison["ci95"]
        print(f"  {comparison['contrast']:<52}"
              f"{comparison['point_difference'] * 100:>+7.2f} pts "
              f"[{lo * 100:+.2f}, {hi * 100:+.2f}]")
    print(f"\nwrote {(RESULTS / 'moderngbert_metrics.json').relative_to(HERE.parent.parent)}")


if __name__ == "__main__":
    main()
