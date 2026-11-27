#!/usr/bin/env python3
"""Evaluate the known-verdict suite with five symbolic checker configurations.

The harness provides:
  - per-pair `engines` capability list (units pairs are STACK-only),
  - `at: units` (ATUnits with sig-figs option + raw input string, after
    stack_unit_si_declare(true)),
  - a fifth checker column: **Math-Verify** (huggingface/math-verify). Input
    LaTeX is rendered by the SAME pinned Maxima via tex1(), so the checker
    judges exactly what STACK would display.

Checkers:
  sympy_default    sympy.simplify(lhs-rhs) == 0
  sympy_engineered rewrite(exp) -> doit -> expand_trig -> trigsimp -> simplify
  maxima_chain     best-of ratsimp/trigrat/radcan/exp+rectform/simpsum
  stack_at         STACK answer test (ATAlgEquiv / ATInt / ATUnits) — production path
  math_verify      math_verify.verify(parse(tex(ta)), parse(tex(sa)))

Usage:
  MAXIMA_URL=http://127.0.0.1:18080/maxima python3 run_suite.py
"""
import argparse
import csv
import json
import multiprocessing as mp
import os
import re
from datetime import datetime, timezone

import requests
import yaml

MAXIMA_URL = os.environ.get("MAXIMA_URL", "http://127.0.0.1:18080/maxima")
ALL_ENGINES = ["sympy_default", "sympy_engineered", "maxima_chain", "stack_at", "math_verify"]
TRANSLATE = [("%pi", "pi"), ("%e", "E"), ("%i", "I"), ("^", "**"), ("inf", "oo")]


def to_sympy(expr_m):
    s = expr_m
    for a, b in TRANSLATE:
        s = s.replace(a, b)
    return s


# ---------- SymPy (subprocess with timeout) ----------
def _sympy_worker(lhs, rhs, assume, strat, q):
    import sympy as sp
    kw = {"positive": True} if assume == "positive" else (
         {"real": True} if assume == "real" else {})
    syms = sp.symbols("x y N t a b c d e f g h", **kw)
    loc = {s.name: s for s in syms}
    loc.update({"Matrix": sp.Matrix, "eye": sp.eye, "Abs": sp.Abs, "Max": sp.Max,
                "Min": sp.Min, "sign": sp.sign, "Sum": sp.Sum})
    e = sp.sympify(lhs, locals=loc) - sp.sympify(rhs, locals=loc)
    if strat == "default":
        r = sp.simplify(e)
    else:
        r = sp.simplify(sp.trigsimp(sp.expand_trig(e.rewrite(sp.exp).doit())))
    if isinstance(r, sp.MatrixBase):
        q.put(bool(sp.simplify(r).is_zero_matrix))
    else:
        q.put(bool(sp.simplify(r) == 0))


def sympy_check(lhs, rhs, assume, strat, timeout=120):
    q = mp.Queue()
    p = mp.Process(target=_sympy_worker, args=(lhs, rhs, assume, strat, q))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return "TIMEOUT"
    if q.empty():
        return "ERROR"
    return "EQUIV" if q.get() else "no"


# ---------- Maxima via GoeMaxima HTTP ----------
def maxima_raw(code, timeout_ms=30000):
    r = requests.post(MAXIMA_URL, data={"input": code, "timeout": str(timeout_ms)},
                      timeout=timeout_ms / 1000 + 10)
    r.raise_for_status()
    return r.text


STRATEGIES = [
    ("ratsimp",  "is(equal(ratsimp(({l})-({r})),0));"),
    ("trigrat",  "is(equal(trigrat(({l})-({r})),0));"),
    ("radcan",   "is(equal(radcan(({l})-({r})),0));"),
    ("exp+rect", "is(equal(ratsimp(rectform(exponentialize(({l})-({r})))),0));"),
    ("simpsum",  "is(equal(ratsimp(ev(({l})-({r}),simpsum)),0));"),
]


EQMARK_RE = re.compile(r"EQMARK:\s*(true|false|unknown)\s*$", re.M)


def maxima_check(lhs, rhs):
    """Winning strategy names, with portfolio-completeness semantics
    (three-valued semantics):
      - any successful winning strategy establishes an equivalence claim,
        even if other strategies errored (one-sided prover);
      - a REJECTION ('none') is decisive only when ALL strategies completed;
      - an incomplete portfolio with no winner is an ERROR, never a rejection
        (a partially/completely dead Maxima service must not score as a
        correct rejection on negative pairs);
      - a strategy COMPLETES only if the response carries the printed
        sentinel `EQMARK: <verdict>` with verdict in {true,false,unknown}
        and no error text. A bare `true` token anywhere in an arbitrary
        body (HTML error page, `true` followed by a crash message) is a
        strategy error, never a win."""
    wins, errors = [], 0
    for name, tmpl in STRATEGIES:
        stmt = tmpl.format(l=lhs, r=rhs).rstrip(";")
        try:
            out = maxima_raw(f'print("EQMARK:", {stmt})$')
        except Exception:
            errors += 1
            continue
        m = EQMARK_RE.search(out)
        if not m or "error" in out.lower():
            errors += 1
        elif m.group(1) == "true":
            wins.append(name)
        # 'false'/'unknown' under the sentinel = completed non-win
    if not wins and errors > 0:
        return None            # incomplete portfolio, no winner -> ERROR
    return wins


AT_RE = re.compile(r"\[\s*(true|false)\s*,\s*(true|false)")


def stack_at_check(pair):
    lhs, rhs, at = str(pair["lhs"]), str(pair["rhs"]), pair.get("at", "algequiv")
    setup = ""
    if at == "int":
        call = f"ATInt({lhs},{rhs},x)"
    elif at == "units":
        setup = "stack_unit_si_declare(true)$ "
        call = f'ATUnits({lhs},{rhs},{pair["at_opt"]},"{pair["raw"]}")'
    else:
        call = f"ATAlgEquiv({lhs},{rhs})"
    try:
        out = maxima_raw(f'{setup}print("ATMARK:", {call})$')
    except Exception as e:
        return "ERROR", str(e)[:120]
    m = AT_RE.search(out.split("ATMARK:")[-1] if "ATMARK:" in out else out)
    tail = " ".join(out.split("ATMARK:")[-1].split())[:200] if "ATMARK:" in out else out[-200:]
    if not m:
        return ("ERROR", tail) if "error" in out.lower() else ("UNPARSED", tail)
    valid, correct = m.group(1) == "true", m.group(2) == "true"
    if not valid:
        return "INVALID", tail
    return ("EQUIV" if correct else "no"), tail


# ---------- Math-Verify (LaTeX rendered by the pinned Maxima) ----------
def maxima_tex(expr):
    try:
        out = maxima_raw(f'print("TEXMARK:", tex1({expr}))$')
    except Exception:
        return None
    m = re.search(r"TEXMARK:\s*(.+?)\s*\(%i", out, re.S)
    if not m:
        m = re.search(r"TEXMARK:\s*(.+)", out)
    return " ".join(m.group(1).split()) if m else None


def _mv_worker(tex_l, tex_r, q):
    from math_verify import parse, verify
    from math_verify.parser import LatexExtractionConfig
    cfg = [LatexExtractionConfig()]
    reference_expression = parse(f"${tex_r}$", extraction_config=cfg)
    ans = parse(f"${tex_l}$", extraction_config=cfg)
    if not reference_expression or not ans:
        q.put("UNPARSED")
        return
    q.put("EQUIV" if verify(reference_expression, ans) else "no")


def mathverify_check(lhs_m, rhs_m, timeout=60):
    tex_l, tex_r = maxima_tex(lhs_m), maxima_tex(rhs_m)
    if not tex_l or not tex_r:
        return "TEX_ERROR"
    q = mp.Queue()
    p = mp.Process(target=_mv_worker, args=(tex_l, tex_r, q))
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return "TIMEOUT"
    if q.empty():
        return "ERROR"
    return q.get()


NONDECISIVE = {"ERROR", "TIMEOUT", "UNPARSED", "TEX_ERROR", "INVALID"}


def classify_result(engine, value):
    """'equiv' | 'reject' | 'error' — three-valued; errors are never verdicts."""
    v = (value or "").strip()
    if engine == "maxima_chain":
        # explicit strategy allowlist — unknown strings are errors, never verdicts
        if v == "none":
            return "reject"
        known = {"ratsimp", "trigrat", "radcan", "exp+rect", "simpsum"}
        return "equiv" if set(v.split(",")) <= known else "error"
    if v == "EQUIV":
        return "equiv"
    if v in NONDECISIVE:
        return "error"
    return "reject"


def score(verdict, result_class):
    """equiv pairs: errors count as failure-to-verify (checker didn't do its
    job). not_equiv pairs: errors are NOT decisive rejections -> excluded
    (None) so they can never inflate the false-positive check."""
    if verdict == "equiv":
        return result_class == "equiv"
    if verdict == "not_equiv":
        return None if result_class == "error" else result_class == "reject"
    return None


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--pairs", default=os.path.join(here, "known_verdict_pairs_v2.yaml"))
    ap.add_argument("--out", default=os.path.join(here, "results"))
    args = ap.parse_args()

    pairs = yaml.safe_load(open(args.pairs, encoding="utf-8"))
    ver = maxima_raw('print("VER:", stackmaximaversion)$')
    stackver = (re.search(r"VER:\s*(\S+)", ver) or [None, "unknown"])[1]
    import sympy
    import math_verify
    versions = {"stackmaxima": stackver, "sympy": sympy.__version__,
                "math_verify": getattr(math_verify, "__version__", "0.9.0")}
    print(f"maxima: {MAXIMA_URL}  {versions}  pairs={len(pairs)}")

    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows = []
    tally = {k: {"pos": [0, 0], "neg": [0, 0]} for k in ALL_ENGINES}

    for p in pairs:
        engines = p.get("engines", ALL_ENGINES)
        lhs_m, rhs_m = str(p["lhs"]), str(p["rhs"])
        lhs_s = p.get("sympy_lhs") or to_sympy(lhs_m)
        rhs_s = p.get("sympy_rhs") or to_sympy(rhs_m)
        assume, verdict = p.get("assume", "none"), p["verdict"]

        res = {}
        res["sympy_default"] = sympy_check(lhs_s, rhs_s, assume, "default") \
            if "sympy_default" in engines else "n/a"
        res["sympy_engineered"] = sympy_check(lhs_s, rhs_s, assume, "engineered") \
            if "sympy_engineered" in engines else "n/a"
        if "maxima_chain" in engines:
            mw = maxima_check(lhs_m, rhs_m)
            res["maxima_chain"] = "ERROR" if mw is None else (",".join(mw) or "none")
        else:
            mw = None
            res["maxima_chain"] = "n/a"
        at, at_raw = stack_at_check(p) if "stack_at" in engines else ("n/a", "")
        res["stack_at"] = at
        res["math_verify"] = mathverify_check(lhs_m, rhs_m) \
            if "math_verify" in engines else "n/a"

        row = {"id": p["id"], "category": p["category"], "verdict": verdict,
               "assume": assume, "lhs": lhs_m, "rhs": rhs_m,
               **res, "stack_at_raw": at_raw}
        for eng in ALL_ENGINES:
            if eng not in engines:
                row[f"{eng}_correct"] = "n/a"
                continue
            ok = score(verdict, classify_result(eng, res[eng]))
            row[f"{eng}_correct"] = "" if ok is None else int(ok)
            if ok is not None:
                b = tally[eng]["pos" if verdict == "equiv" else "neg"]
                b[0] += int(ok)
                b[1] += 1
        rows.append(row)
        print(f"  {p['id']:<26} [{verdict:>9}] " +
              " ".join(f"{e.split('_')[-1]}={res[e]}" for e in ALL_ENGINES))

    csv_path = os.path.join(args.out, f"{ts}_known_verdict_v2.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {"timestamp": ts, "maxima_url": MAXIMA_URL, "versions": versions,
               "pairs": len(pairs), "tally": {
                   e: {"equiv": f"{t['pos'][0]}/{t['pos'][1]}",
                       "not_equiv": f"{t['neg'][0]}/{t['neg'][1]}"}
                   for e, t in tally.items()}}
    with open(os.path.join(args.out, f"{ts}_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary["tally"], indent=2))
    print(f"rows -> {csv_path}")


if __name__ == "__main__":
    main()
