#!/usr/bin/env python3
"""randomized-instance study — the ONE held-out draw (PROTOCOL.md §2). Run exactly once, after
the protocol + harness are committed.

For each candidate template (shuffled, RNG seed 20260718, topic cap 4):
  - anchor = first author-deployed seed, if any;
  - fresh seeds drawn from 9201.. sequentially, kept only if the SHA-256 of
    the exact final model prompt is new for the template; stop at 4 unique or
    give up after 12 candidates (template replaced, logged);
  - EVERY kept instance passes the gate: render -> structured teacher answer
    -> grade(teacher) -> isgradable && isclose(score, 1).

Outputs:
  selection.csv        template, topic, input, anchor_seed, fresh_seeds
  instances.jsonl      model-facing: prompt_text, prompt_sha256, teacher answers
  sealed_meta.jsonl    question_note etc. — NEVER model-facing
  draw_log.json        replacements + gate failures (audit trail)

Refuses to run if selection.csv already exists.
"""
import csv
import hashlib
import json
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "not_included/worked_solution_generation"))
from pilot_select import load_all_stack  # noqa: E402
from stack_client import render_instance, grade, StackAPIError  # noqa: E402
from run import USER_TMPL, SYSTEM  # noqa: E402  (prompt shape for the hash)

DRAW_SEED = 20260718
N_TEMPLATES = 60
TOPIC_CAP = 4
FRESH_BASE = 9201
MAX_SEED_TRIES = 12
RAND = re.compile(r"\brand\w*\s*\(")


def eligible_pool():
    import pyarrow.parquet as pq
    src = pq.read_table(
        ROOT / "not_included/source/all-00000-of-00001.parquet",
        columns=["rc_id", "deployed_seeds", "is_auto_gradable"]).to_pandas()
    meta = {r.rc_id: ([] if r.deployed_seeds is None else [int(x) for x in r.deployed_seeds],
                      bool(r.is_auto_gradable)) for r in src.itertuples()}
    expert_reference = {r["rc_id"] for r in csv.DictReader(
        open(ROOT / "not_included/expert_reference_source.csv", encoding="utf-8-sig"))}
    excl = set(expert_reference)
    for f in [ROOT / "not_included/worked_solution_generation/worked_solution_development_selection_1.csv",
              ROOT / "not_included/worked_solution_generation/worked_solution_development_selection_2.csv",
              ROOT / "not_included/randomized_instance_selection.csv"]:            # 40 dev templates
        excl |= {r["rc_id"] for r in csv.DictReader(open(f, encoding="utf-8"))}
    pool = []
    for q in load_all_stack():
        rc = q["rc_id"]
        if not rc or rc in excl or rc not in meta:
            continue
        seeds, gradable = meta[rc]
        if not gradable or not RAND.search(q["qv"]) or len(q["inputs"]) != 1:
            continue
        name_t, tans, ty = q["inputs"][0]
        if not tans or (ty or "algebraic") != "algebraic":
            continue
        ats = set(q["answertests"].split("|")) - {""}
        if ats != {"AlgEquiv"}:
            continue
        if "<img" in q["qt"].lower() or "pluginfile" in q["qt"].lower():
            continue
        if len(q["qt"]) > 2500:
            continue
        pool.append((q, seeds))
    return pool


def frag_of(xml_all, rc):
    m = re.search(rf'<question type="stack">(?:(?!</question>).)*?'
                  rf'<idnumber>{rc}</idnumber>.*?</question>', xml_all, re.S)
    if not m:
        raise RuntimeError(f"canonical STACK XML block not found for {rc}")
    return m.group(0)


def clean_frozen_state():
    """Require committed harness and every file that defines the draw frame."""
    frozen_inputs = [
        ROOT / "not_included/quiz-Math1-Math2.xml",
        ROOT / "not_included/quiz-Numeric.xml",
        ROOT / "not_included/expert_reference_source.csv",
        ROOT / "not_included/source/all-00000-of-00001.parquet",
        ROOT / "not_included/worked_solution_generation/worked_solution_development_selection_1.csv",
        ROOT / "not_included/worked_solution_generation/worked_solution_development_selection_2.csv",
        ROOT / "not_included/randomized_instance_selection.csv",
    ]
    missing = [str(path) for path in frozen_inputs if not path.exists()]
    if missing:
        sys.exit(f"REFUSING held-out draw: frozen inputs missing: {missing}")
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", str(HERE),
         *map(str, frozen_inputs)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        sys.exit("REFUSING held-out draw: protocol/harness is not a clean "
                 "committed tree. Commit it before drawing.\n" + dirty)
    return commit, {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in frozen_inputs
    }


def gate_instance(frag, seed, input_name):
    """render -> teacher answer -> grade(teacher) == 1. Returns (inst, err)."""
    try:
        ins = render_instance(frag, seed)
    except StackAPIError as e:
        return None, f"render: {e}"
    ta = ins["teacher_answers"].get(input_name)
    if not ta:
        return None, "no structured teacher answer"
    try:
        g = grade(frag, seed, {input_name: ta})
    except StackAPIError as e:
        return None, f"grade: {e}"
    if not (g["isgradable"] and g["score"] is not None
            and abs(g["score"] - 1.0) < 1e-9):
        return None, f"teacher round-trip score={g['score']}"
    return ins, None


def main():
    if (HERE / "selection.csv").exists():
        sys.exit("selection.csv exists — the held-out draw already happened. "
                 "A redraw requires a new protocol version and dated amendment.")
    harness_commit, input_sha256 = clean_frozen_state()
    xml_all = (ROOT / "not_included/quiz-Math1-Math2.xml").read_text(encoding="utf-8") + \
              (ROOT / "not_included/quiz-Numeric.xml").read_text(encoding="utf-8")
    pool = eligible_pool()
    rng = random.Random(DRAW_SEED)
    rng.shuffle(pool)
    print(f"eligible pool: {len(pool)} templates")

    picked, per_source_bank_category = [], {}
    log = {"draw_seed": DRAW_SEED, "harness_commit": harness_commit,
           "input_sha256": input_sha256,
           "pool": len(pool), "replaced": [],
           "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    inst_rows, sealed_rows = [], []

    for q, seeds in pool:
        if len(picked) == N_TEMPLATES:
            break
        if per_source_bank_category.get(q["topic"], 0) >= TOPIC_CAP:
            continue
        rc = q["rc_id"]
        input_name = q["inputs"][0][0]
        frag = frag_of(xml_all, rc)
        got, hashes, tried, fail = [], set(), 0, None
        # anchor first (if deployed)
        anchor_seed = seeds[0] if seeds else None
        if anchor_seed is not None:
            ins, err = gate_instance(frag, anchor_seed, input_name)
            if err:
                log["replaced"].append({"rc_id": rc, "why": f"anchor {err}"})
                continue
            user_prompt = USER_TMPL.format(qt=ins["prompt_text"], input_name=input_name)
            anchor_hash = hashlib.sha256((SYSTEM + user_prompt).encode()).hexdigest()
            ins["_prompt_sha"] = anchor_hash
            hashes.add(anchor_hash)
            got.append(("anchor", anchor_seed, ins))
        # fresh seeds with prompt-hash uniqueness
        cand = FRESH_BASE
        fresh = []
        while len(fresh) < 4 and tried < MAX_SEED_TRIES:
            while cand in seeds or cand == anchor_seed:
                cand += 1
            ins, err = gate_instance(frag, cand, input_name)
            tried += 1
            if err:
                fail = err
                cand += 1
                continue
            user_prompt = USER_TMPL.format(qt=ins["prompt_text"], input_name=input_name)
            h = hashlib.sha256((SYSTEM + user_prompt).encode()).hexdigest()
            if h in hashes:
                cand += 1
                continue
            hashes.add(h)
            ins["_prompt_sha"] = h
            fresh.append((cand, ins))
            cand += 1
        if len(fresh) < 4:
            log["replaced"].append({"rc_id": rc, "why": f"only {len(fresh)} unique "
                                    f"instances in {tried} tries (last: {fail})"})
            continue
        # accept template
        per_source_bank_category[q["topic"]] = per_source_bank_category.get(q["topic"], 0) + 1
        picked.append({"rc_id": rc, "name": q["name"], "topic": q["topic"],
                       "input_name": input_name,
                       "anchor_seed": anchor_seed if anchor_seed is not None else "",
                       "fresh_seeds": " ".join(str(s) for s, _ in fresh),
                       "n_deployed": len(seeds)})
        for kind, seed, ins in (got + [("fresh", s, i) for s, i in fresh]):
            user_prompt = USER_TMPL.format(qt=ins["prompt_text"], input_name=input_name)
            h = ins.get("_prompt_sha") or hashlib.sha256(
                (SYSTEM + user_prompt).encode()).hexdigest()
            inst_rows.append({"rc_id": rc, "name": q["name"], "seed": seed,
                              "kind": kind, "input_name": input_name,
                              "prompt_text": ins["prompt_text"],
                              "prompt_sha256": h,
                              "teacher_answer": ins["teacher_answers"][input_name]})
            sealed_rows.append({"rc_id": rc, "seed": seed,
                                "question_note": ins["question_note"]})
        print(f"  [{len(picked)}/60] {q['topic'][:24]:24} {q['name'][:44]} "
              f"anchor={'y' if anchor_seed is not None else '-'}")

    if len(picked) < N_TEMPLATES:
        sys.exit(f"pool exhausted at {len(picked)} templates — protocol violation, "
                 "do not proceed")

    with (HERE / "selection.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(picked[0].keys()))
        w.writeheader(); w.writerows(picked)
    with (HERE / "instances.jsonl").open("w", encoding="utf-8") as fh:
        for r in inst_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (HERE / "sealed_meta.jsonl").open("w", encoding="utf-8") as fh:
        for r in sealed_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    k = sum(1 for r in picked if r["anchor_seed"] != "")
    log["templates"] = len(picked)
    log["k_anchor"] = k
    log["rows_per_model"] = 60 * 4 + k + 12 * 2 * 2
    (HERE / "draw_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"\nDRAW COMPLETE: 60 templates, k={k} anchors, "
          f"{len(inst_rows)} gated instances, {len(log['replaced'])} replacements "
          f"-> rows/model = {log['rows_per_model']}")


if __name__ == "__main__":
    main()
