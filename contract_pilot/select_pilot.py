#!/usr/bin/env python3
"""Contract pilot — one-time stratified draw from the frozen gated pool (PROTOCOL §3)."""
import argparse, csv, hashlib, json, random, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).parent
SEED = 20260916
QUOTA = {"subst": 3, "numerical": 4, "int": 5, "form": 8}   # draw order: smallest family first
TOPIC_CAP = 6

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    if (HERE / "selection.csv").exists() and not a.dry_run:
        sys.exit("selection.csv exists — the draw already happened; a redraw needs a protocol amendment")
    pool = [json.loads(l) for l in (HERE / "inputs/gated_pool.jsonl").read_text(encoding="utf-8").splitlines()]
    covered = {json.loads(l)["rc_id"] for l in (HERE / "inputs/gated_pool_coverage.jsonl").read_text(encoding="utf-8").splitlines() if json.loads(l)["bridge_covered"]}
    passing = [r for r in pool if r["pass"] and r["n_valid"] == 4 and r["rc_id"] in covered]
    rng = random.Random(SEED)
    picked, per_topic, skipped = [], Counter(), []
    for fam, n in QUOTA.items():
        cands = sorted([r for r in passing if r["family"] == fam], key=lambda r: r["rc_id"])
        rng.shuffle(cands)
        taken = 0
        for r in cands:
            if taken == n: break
            if per_topic[r["topic"]] >= TOPIC_CAP:
                skipped.append({"rc_id": r["rc_id"], "why": f"topic cap {r['topic']}"}); continue
            picked.append(r); per_topic[r["topic"]] += 1; taken += 1
        if taken < n: sys.exit(f"family {fam}: only {taken}/{n} available — protocol violation")
    print(f"picked {len(picked)}: " + ", ".join(f"{k}={v}" for k, v in Counter(r['family'] for r in picked).items()))
    print("topics:", dict(per_topic)); print("tests:", dict(Counter(r["tests"] for r in picked)))
    for r in picked: print(f"  {r['family']:9} {r['tests'][:24]:24} {r['topic'][:18]:18} {r['name'][:50]}")
    if a.dry_run: return
    with (HERE / "selection.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rc_id", "name", "topic", "family", "tests", "input_name", "fresh_seeds"]); w.writeheader()
        for r in picked:
            w.writerow({"rc_id": r["rc_id"], "name": r["name"], "topic": r["topic"], "family": r["family"], "tests": r["tests"],
                        "input_name": r["input"], "fresh_seeds": " ".join(str(i["seed"]) for i in r["instances"])})
    with (HERE / "instances.jsonl").open("w", encoding="utf-8") as fh:
        for r in picked:
            for i in r["instances"]:
                fh.write(json.dumps({"rc_id": r["rc_id"], "name": r["name"], "seed": i["seed"], "kind": "fresh", "input_name": r["input"],
                                     "prompt_text": i["prompt_text"], "prompt_sha256": i["prompt_sha256"], "teacher_answer": i["teacher_answer"]}, ensure_ascii=False) + "\n")
    log = {"draw_seed": SEED, "quota": QUOTA, "topic_cap": TOPIC_CAP, "pool_pass": len(passing), "picked": len(picked), "skipped": skipped,
           "input_sha256": {f"inputs/{n}": sha(HERE / "inputs" / n) for n in ("gated_pool.jsonl", "gated_pool_coverage.jsonl", "candidates.csv", "gate_pool.py")},
           "protocol_sha256": sha(HERE / "PROTOCOL.md"), "drawn": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (HERE / "draw_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("DRAW COMPLETE -> selection.csv, instances.jsonl, draw_log.json")

if __name__ == "__main__": main()
