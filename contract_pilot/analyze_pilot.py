#!/usr/bin/env python3
"""Contract pilot — prespecified analysis (PROTOCOL §6): both disagreement directions,
coverage, distinct questions, by family and test set; descriptive per-profile rates."""
import csv, json, os, sys
from collections import Counter, defaultdict
from pathlib import Path
HERE = Path(__file__).parent; DATA = Path(os.environ.get("PILOT_DATA_DIR", HERE))

def b(v): return True if v in ("1", 1, True) else False if v in ("0", 0, False) else None

def main():
    partial = "--partial" in sys.argv
    sel = {r["rc_id"]: r for r in csv.DictReader(open(DATA / "selection.csv", encoding="utf-8"))}
    rows = list(csv.DictReader(open(DATA / "results.csv", encoding="utf-8")))
    models = sorted({r["model"] for r in rows}); expected = len(sel) * 4 * len(models)
    if len(rows) != expected and not partial: sys.exit(f"grid incomplete: {len(rows)}/{expected} rows (use --partial for interim)")
    out = {"rows": len(rows), "expected": expected, "questions": len(sel), "models": models, "per_profile": {}, "methods": {}, "by_family": {}, "by_tests": {}}
    for m in models:
        mr = [r for r in rows if r["model"] == m]; st = Counter(r["status"] for r in mr)
        out["per_profile"][m] = {"full_credit": st["correct"], "wrong": st["wrong"], "partial": st["partial"], "format_failure": st["format_failure"],
                                 "syntax_invalid": st["syntax_invalid"], "empty": st["empty"], "n": len(mr)}
    dec = [r for r in rows if r["status"] in ("correct", "wrong")]
    def table(sub):
        t = {}
        for arm, f in (("string", "string_eq"), ("sympy", "sympy_eq"), ("math_verify", "math_verify_eq")):
            cov = [r for r in sub if b(r[f]) is not None]
            a = [r for r in cov if r["status"] == "correct" and b(r[f]) is False]
            bb = [r for r in cov if r["status"] == "wrong" and b(r[f]) is True]
            t[arm] = {"covered": len(cov), "decisive": len(sub), "stack_grants_comparator_denies": len(a), "questions_a": len({r["rc_id"] for r in a}),
                      "comparator_accepts_stack_denies": len(bb), "questions_b": len({r["rc_id"] for r in bb})}
        return t
    out["methods"] = table(dec)
    fams = defaultdict(list); tests = defaultdict(list)
    for r in dec: fams[sel[r["rc_id"]]["family"]].append(r); tests[sel[r["rc_id"]]["tests"]].append(r)
    out["by_family"] = {k: table(v) for k, v in sorted(fams.items())}; out["by_tests"] = {k: table(v) for k, v in sorted(tests.items())}
    out["partial_scores_strictly_between_0_and_1"] = sum(1 for r in rows if r["status"] == "partial")
    (DATA / "analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["methods"], indent=1)); print("per profile:", json.dumps(out["per_profile"], indent=1))

if __name__ == "__main__": main()
