#!/usr/bin/env python3
"""Reproduction 1: independent recount of analysis.json from results.csv (pandas implementation)."""
import json, sys
from pathlib import Path
import pandas as pd
HERE = Path(__file__).resolve().parent.parent
r = pd.read_csv(HERE / "results.csv", dtype={"sympy_eq": "object", "math_verify_eq": "object", "string_eq": "object"})
a = json.load(open(HERE / "analysis.json"))
def tb(x): return None if pd.isna(x) or x == "" else str(x).strip() in ("1", "1.0", "True")
d = r[r.status.isin(["correct", "wrong"])].copy(); ok = True
for arm, col in (("string", "string_eq"), ("sympy", "sympy_eq"), ("math_verify", "math_verify_eq")):
    v = d[col].map(tb); cov = d[v.notna()]; vv = v[v.notna()]
    A = cov[(cov.status == "correct") & (vv == False)]; B = cov[(cov.status == "wrong") & (vv == True)]
    mine = (len(cov), len(A), A.rc_id.nunique(), len(B), B.rc_id.nunique()); ref = a["methods"][arm]
    theirs = (ref["covered"], ref["stack_grants_comparator_denies"], ref["questions_a"], ref["comparator_accepts_stack_denies"], ref["questions_b"])
    print(arm, mine, theirs, "MATCH" if mine == theirs else "MISMATCH"); ok &= mine == theirs
print("partial", int((r.status == "partial").sum()), a["partial_scores_strictly_between_0_and_1"])
sys.exit(0 if ok else 1)
