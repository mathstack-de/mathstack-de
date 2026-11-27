#!/usr/bin/env python3
"""Reproducible Z3 proofs for three piecewise identities.

The known-verdict suite documents that all five compared checkers fail (or nearly all
fail) on min/max/signum recomposition identities. These identities are
semialgebraic; encoded with If-terms they are decided by Z3 in milliseconds:
`unsat` for the negated identity == the identity holds over the reals.

The harness proves only these three identities.

Run: python3 z3_piecewise_proofs.py   (asserts all three are unsat)
"""
import time

import z3

x, y = z3.Reals("x y")
Abs = lambda a: z3.If(a >= 0, a, -a)
Max = lambda a, b: z3.If(a >= b, a, b)
Min = lambda a, b: z3.If(a <= b, a, b)
Sgn = lambda a: z3.If(a > 0, z3.RealVal(1), z3.If(a < 0, z3.RealVal(-1), z3.RealVal(0)))

IDENTITIES = [
    ("max(x,0) == (x+|x|)/2",        Max(x, z3.RealVal(0)) == (x + Abs(x)) / 2),
    ("max(x,y)+min(x,y) == x+y",     Max(x, y) + Min(x, y) == x + y),
    ("|x| == x*signum(x)",           Abs(x) == x * Sgn(x)),
]


def main():
    all_ok = True
    for name, ident in IDENTITIES:
        s = z3.Solver()
        s.add(z3.Not(ident))
        t0 = time.time()
        r = s.check()
        ms = (time.time() - t0) * 1000
        ok = r == z3.unsat
        all_ok &= ok
        print(f"{name:<32} -> {r}  ({ms:.1f} ms)  {'PROVED' if ok else 'NOT PROVED'}")
    assert all_ok, "at least one identity was not proved"
    print("all three identities proved (negation unsat over the reals)")


if __name__ == "__main__":
    main()
