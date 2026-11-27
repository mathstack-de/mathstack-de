#!/usr/bin/env python3
"""Randomized-instance study: predeclared analysis (PROTOCOL_frozen.md §7).
Runs only on a complete
grid (grade.py must have exited 0). Bootstrap clustered over templates.

Outputs analysis.json + console report:
  - fresh accuracy per model with 95% cluster-bootstrap CI
  - anchor vs fresh (anchor templates only, paired per template)
  - per-template consistency (all/some/none)
  - ranking stability across single-seed columns
  - checker disagreement table (false-accept/false-reject vs STACK)
  - replicate decision rule: same-prompt vs cross-seed disagreement
"""
import csv
import hashlib
import json
import os
import random
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent
LEGACY_DATA = Path(os.environ.get("STUDY_DATA_DIR", HERE))
DATA = Path(os.environ.get("STUDY_OUTPUT_DIR", LEGACY_DATA))
BOOT = 2000
RNG = random.Random(20260719)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ci(vals_by_template, stat):
    """95% bootstrap CI clustered over templates."""
    keys = list(vals_by_template)
    stats = []
    for _ in range(BOOT):
        sample = [vals_by_template[RNG.choice(keys)] for _ in keys]
        stats.append(stat(sample))
    stats.sort()
    return stats[int(0.025 * BOOT)], stats[int(0.975 * BOOT)]


def acc_stat(clusters):
    flat = [x for c in clusters for x in c]
    return sum(flat) / len(flat) if flat else 0.0


def pairwise_disagreement(values):
    pairs = list(combinations(values, 2))
    return sum(left != right for left, right in pairs) / len(pairs)


def rank_groups(scores):
    """Tie-aware descending ranking represented as ordered model groups."""
    groups = []
    for model in sorted(scores, key=lambda item: (-scores[item], item)):
        if not groups or scores[model] != scores[groups[-1][0]]:
            groups.append([model])
        else:
            groups[-1].append(model)
    return groups


def main():
    manifest_path = DATA / "grade_manifest.json"
    if not manifest_path.exists():
        sys.exit("grade_manifest.json missing — grade.py did not close a complete grid")
    grade_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results_path = DATA / "results.csv"
    if grade_manifest["sha256"]["results"] != file_sha(results_path):
        sys.exit("results.csv does not match the complete-grid grade manifest")
    rows = list(csv.DictReader(open(results_path, encoding="utf-8")))
    if len(rows) != grade_manifest["rows"]:
        sys.exit("results row count does not match grade manifest")
    models = sorted({r["model"] for r in rows})
    if models != sorted(grade_manifest["models"]):
        sys.exit("results model set does not match grade manifest")
    out = {"models": {}, "grade_manifest_sha256": file_sha(manifest_path)}

    print("=== Randomized-instance analysis (STACK /grade authoritative) ===\n")
    for m in models:
        mine = [r for r in rows if r["model"] == m]
        fresh = [r for r in mine if r["kind"] == "fresh" and r["rep"] == "0"]
        by_t = defaultdict(list)
        for r in fresh:
            by_t[r["rc_id"]].append(r["status"] == "correct")
        lo, hi = ci(by_t, acc_stat)
        acc = acc_stat(list(by_t.values()))
        full = sum(1 for v in by_t.values() if all(v))
        none = sum(1 for v in by_t.values() if not any(v))
        part = len(by_t) - full - none
        # anchor vs fresh, paired on anchor templates.
        # Two views, both reported (the strict view conflates a model's
        # own format-failure asymmetry with a genuine accuracy difference). "Adjusted" excludes format_failure rows and
        # restricts to decisive STACK verdicts on BOTH arms before pairing.
        anchor_all = {r["rc_id"]: r for r in mine if r["kind"] == "anchor"}
        fresh_all_by_t = defaultdict(list)
        for r in mine:
            if r["kind"] == "fresh" and r["rep"] == "0":
                fresh_all_by_t[r["rc_id"]].append(r)

        def paired_delta(decisive_only):
            deltas = {}
            for t, a_row in anchor_all.items():
                if decisive_only and a_row["status"] not in ("correct", "wrong", "partial"):
                    continue
                if not decisive_only and a_row["status"] == "format_failure":
                    continue
                fresh_rows = fresh_all_by_t.get(t, [])
                if decisive_only:
                    fresh_rows = [r for r in fresh_rows
                                 if r["status"] in ("correct", "wrong", "partial")]
                else:
                    fresh_rows = [r for r in fresh_rows if r["status"] != "format_failure"]
                if not fresh_rows:
                    continue
                a_correct = 1.0 if a_row["status"] == "correct" else 0.0
                f_acc = sum(r["status"] == "correct" for r in fresh_rows) / len(fresh_rows)
                deltas[t] = a_correct - f_acc
            return deltas

        deltas = {t: (int(anchor_all[t]["status"] == "correct")
                      - sum(by_t[t]) / len(by_t[t]))
                  for t in anchor_all if t in by_t}
        d_mean = sum(deltas.values()) / len(deltas) if deltas else None
        d_ci = ci({t: [d] for t, d in deltas.items()},
                  lambda cl: sum(x for c in cl for x in c) / len(cl)) if deltas else None

        adj_deltas = paired_delta(decisive_only=True)
        adj_mean = sum(adj_deltas.values()) / len(adj_deltas) if adj_deltas else None
        adj_ci = ci({t: [d] for t, d in adj_deltas.items()},
                    lambda cl: sum(x for c in cl for x in c) / len(cl)) if adj_deltas else None
        # format compliance
        n_all = len(mine)
        fmt_fail = sum(1 for r in mine if r["status"] in ("format_failure", "empty"))
        # Replicate rule: six pairwise comparisons on each side, paired on the
        # same first-12 templates (2 prompts x C(3,2) vs C(4,2)).
        rep_groups = defaultdict(list)
        for r in mine:
            if r["kind"] in ("fresh", "replicate"):
                rep_groups[(r["rc_id"], r["seed"])].append(r["status"] == "correct")
        same_by_template = defaultdict(list)
        for (rc, _seed), group in rep_groups.items():
            if len(group) == 3:
                same_by_template[rc].append(pairwise_disagreement(group))
        same_by_template = {
            rc: [sum(values) / 2] for rc, values in same_by_template.items()
            if len(values) == 2
        }
        cross_by_template = {
            rc: [pairwise_disagreement(by_t[rc])] for rc in same_by_template
            if len(by_t.get(rc, [])) == 4
        }
        if same_by_template and len(cross_by_template) == len(same_by_template):
            sp_dis = acc_stat(list(same_by_template.values()))
            cs_dis = acc_stat(list(cross_by_template.values()))
            sp_ci = ci(same_by_template, acc_stat)
            cs_ci = ci(cross_by_template, acc_stat)
            delta_by_template = {
                rc: [cross_by_template[rc][0] - same_by_template[rc][0]]
                for rc in same_by_template
            }
            delta = acc_stat(list(delta_by_template.values()))
            delta_ci = ci(delta_by_template, acc_stat)
            if delta_ci[0] > 0:
                separation = "cross_seed_exceeds_same_prompt"
            elif delta_ci[1] < 0:
                separation = "same_prompt_exceeds_cross_seed"
            else:
                separation = "inseparable_delta_ci_contains_zero"
        else:
            sp_dis = cs_dis = sp_ci = cs_ci = delta = delta_ci = separation = None
        out["models"][m] = {
            "fresh_acc": acc, "fresh_ci": [lo, hi],
            "consistency_all_some_none": [full, part, none],
            "anchor_minus_fresh_strict": d_mean, "anchor_delta_ci_strict": d_ci,
            "anchor_minus_fresh_adjusted": adj_mean, "anchor_delta_ci_adjusted": adj_ci,
            "anchor_adjustment_note": ("excludes format_failure rows on both arms "
                                      "and restricts to decisive STACK verdicts; "
                                      "the strict figure conflates format-failure "
                                      "asymmetry with accuracy"),
            "format_failure_rate": fmt_fail / n_all if n_all else None,
            "same_prompt_disagreement": sp_dis,
            "same_prompt_disagreement_ci": sp_ci,
            "cross_seed_disagreement": cs_dis,
            "cross_seed_disagreement_ci": cs_ci,
            "cross_minus_same_prompt": delta,
            "cross_minus_same_prompt_ci": delta_ci,
            "variant_vs_decoding_decision": separation,
        }
        print(f"{m}")
        print(f"  fresh accuracy: {acc:.3f}  [{lo:.3f}, {hi:.3f}]  "
              f"(templates all/some/none = {full}/{part}/{none})")
        if d_mean is not None:
            print(f"  anchor - fresh (strict):   {d_mean:+.3f}  "
                  f"[{d_ci[0]:+.3f}, {d_ci[1]:+.3f}] on {len(deltas)} templates")
        if adj_mean is not None:
            sig = "excludes zero" if (adj_ci[0] > 0 or adj_ci[1] < 0) else "CI touches zero"
            print(f"  anchor - fresh (adjusted): {adj_mean:+.3f}  "
                  f"[{adj_ci[0]:+.3f}, {adj_ci[1]:+.3f}] on {len(adj_deltas)} templates ({sig})")
        print(f"  format failures: {fmt_fail}/{n_all}")
        if sp_dis is not None:
            print(f"  same-prompt disagreement {sp_dis:.2f} "
                  f"[{sp_ci[0]:.2f}, {sp_ci[1]:.2f}] vs cross-seed "
                  f"{cs_dis:.2f} [{cs_ci[0]:.2f}, {cs_ci[1]:.2f}] -> "
                  f"delta {delta:+.2f} [{delta_ci[0]:+.2f}, {delta_ci[1]:+.2f}] "
                  f"-> {separation}")
        print()

    # ranking stability: order under each seed column vs aggregate
    seeds_cols = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["kind"] == "fresh" and r["rep"] == "0":
            # seed position within its template = column index
            seeds_cols[r["rc_id"]][r["seed"]] = None
    col_of = {}
    for rc, sd in seeds_cols.items():
        for i, s in enumerate(sorted(sd, key=int)):
            col_of[(rc, s)] = i
    col_acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["kind"] == "fresh" and r["rep"] == "0":
            col_acc[col_of[(r["rc_id"], r["seed"])]][r["model"]].append(
                r["status"] == "correct")
    rankings, column_scores = {}, {}
    for col, per_m in sorted(col_acc.items()):
        scores = {m: sum(per_m[m]) / len(per_m[m]) for m in per_m}
        rankings[f"seed_col_{col}"] = rank_groups(scores)
        column_scores[f"seed_col_{col}"] = scores
    aggregate_scores = {model: out["models"][model]["fresh_acc"] for model in models}
    aggregate_ranking = rank_groups(aggregate_scores)
    out["aggregate_accuracy"] = aggregate_scores
    out["aggregate_ranking"] = aggregate_ranking
    out["ranking_by_seed_column"] = rankings
    out["accuracy_by_seed_column"] = column_scores
    pairs = [(a, b) for i, a in enumerate(models) for b in models[i + 1:]]
    pairwise = {}
    for a, b in pairs:
        signs = []
        for scores in column_scores.values():
            delta = scores[a] - scores[b]
            signs.append(0 if delta == 0 else (1 if delta > 0 else -1))
        pairwise[f"{a}__vs__{b}"] = signs
    aggregate_signs = {}
    for a, b in pairs:
        delta = aggregate_scores[a] - aggregate_scores[b]
        aggregate_signs[f"{a}__vs__{b}"] = (
            0 if delta == 0 else (1 if delta > 0 else -1)
        )
    stable = all(all(sign == aggregate_signs[pair] for sign in signs)
                 for pair, signs in pairwise.items())
    out["pairwise_order_by_seed_column"] = pairwise
    out["pairwise_order_aggregate"] = aggregate_signs
    out["pairwise_ranking_stable"] = stable
    print(f"ranking stability across seed columns: "
          f"{'PAIRWISE-STABLE' if stable else 'PAIRWISE CHANGES/TIES'}")
    print("  aggregate: " + " > ".join(
        " = ".join(model[:20] for model in group) for group in aggregate_ranking
    ))
    for column, groups in rankings.items():
        rendered = " > ".join(
            " = ".join(model[:20] for model in group) for group in groups
        )
        print(f"  {column}: {rendered}")

    # checker table -- coverage + conditional agreement, correct denominators
    print("\nchecker vs STACK (decisive STACK rows = correct/wrong/partial):")
    decisive = [r for r in rows if r["status"] in ("correct", "wrong", "partial")]
    stack_correct = [r for r in decisive if r["status"] == "correct"]
    print(f"  decisive rows: {len(decisive)}  of which STACK-correct: {len(stack_correct)}")
    for arm in ("sympy_eq", "math_verify_eq", "string_eq"):
        dec = [r for r in decisive if r[arm] != ""]
        coverage = len(dec) / len(decisive) if decisive else 0.0
        fa = sum(1 for r in dec if r[arm] == "1" and r["status"] != "correct")
        fr = sum(1 for r in dec if r[arm] == "0" and r["status"] == "correct")
        agree = sum(1 for r in dec
                    if (r[arm] == "1") == (r["status"] == "correct"))
        cond_agree = agree / len(dec) if dec else 0.0
        fr_of_correct = fr / len(stack_correct) if stack_correct else 0.0
        out.setdefault("checkers", {})[arm] = {
            "decisive_denominator": len(decisive), "coverage_n": len(dec),
            "coverage_pct": coverage, "conditional_agreement_pct": cond_agree,
            "false_accept": fa, "false_reject": fr,
            "false_reject_pct_of_stack_correct": fr_of_correct}
        print(f"  {arm:16} coverage={len(dec):4}/{len(decisive)} ({coverage:.1%})  "
              f"agree={cond_agree:.1%}  false_accept={fa:3}  "
              f"false_reject={fr:3} ({fr_of_correct:.1%} of STACK-correct)")

    (DATA / "analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("\n-> analysis.json")


if __name__ == "__main__":
    main()
