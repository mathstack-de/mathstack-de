#!/usr/bin/env python3
"""Apply error-aware scoring to a known-verdict result CSV (no engine is
re-run):

  equiv pairs      "EQUIV" is correct; anything else (incl. errors) is a
                   failure to verify — errors additionally reported.
  not_equiv pairs  only DECISIVE results count: "no"/"none" (no equivalence
                   claim) are correct-no-false-positive; ERROR/TIMEOUT/
                   UNPARSED/TEX_ERROR/INVALID are excluded from the
                   denominator and reported as errors.

Usage: python3 rescore.py [results.csv]
Writes <input>_rescored_summary.json and prints the table.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ENGINES = ["stack_at", "sympy_default", "sympy_engineered", "maxima_chain", "math_verify"]
NONDECISIVE = {"ERROR", "TIMEOUT", "UNPARSED", "TEX_ERROR", "INVALID"}


def classify(engine, value):
    """-> 'equiv' | 'reject' | 'error' | 'na'"""
    v = (value or "").strip()
    if v in ("n/a", ""):
        return "na"
    if engine == "maxima_chain":
        # comma-joined winning strategy names, or "none" (one-sided: no claim).
        # Only EXPLICITLY known strategy names count as an equivalence claim —
        # anything else (future error strings etc.) is an error, never a verdict.
        if v == "none":
            return "reject"
        known = {"ratsimp", "trigrat", "radcan", "exp+rect", "simpsum"}
        return "equiv" if set(v.split(",")) <= known else "error"
    if v == "EQUIV":
        return "equiv"
    if v in NONDECISIVE:
        return "error"
    return "reject"   # "no"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        HERE / "results.csv"
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    scored = [r for r in rows if r["verdict"] in ("equiv", "not_equiv")]

    out = {}
    for e in ENGINES:
        pos_ok = pos_n = pos_err = 0
        neg_ok = neg_dec = neg_err = 0
        for r in scored:
            c = classify(e, r.get(e))
            if c == "na":
                continue
            if r["verdict"] == "equiv":
                pos_n += 1
                pos_ok += (c == "equiv")
                pos_err += (c == "error")
            else:
                if c == "error":
                    neg_err += 1
                else:
                    neg_dec += 1
                    neg_ok += (c == "reject")
        out[e] = {"equiv": f"{pos_ok}/{pos_n}" + (f" ({pos_err} errors)" if pos_err else ""),
                  "not_equiv_decisive": f"{neg_ok}/{neg_dec}",
                  "not_equiv_errors": neg_err,
                  "false_positives": neg_dec - neg_ok}

    dst = src.with_name(src.stem + "_rescored_summary.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=2)
    print(f"{'checker':<18} {'equiv':<18} {'non-equiv decisive':<20} errors  false-pos")
    for e, t in out.items():
        print(f"{e:<18} {t['equiv']:<18} {t['not_equiv_decisive']:<20} "
              f"{t['not_equiv_errors']:<7} {t['false_positives']}")
    print(f"-> {dst}")


if __name__ == "__main__":
    main()
