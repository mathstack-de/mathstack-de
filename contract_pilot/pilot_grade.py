#!/usr/bin/env python3
"""Contract pilot — grade answers with the pinned STACK engine + diagnostics (PROTOCOL §5).
Reuses the functions of variant_study/grade.py unchanged. Policy: raw-v1+brace-off only."""
import csv, hashlib, json, os, subprocess, sys
from pathlib import Path
HERE = Path(__file__).parent; STUDY = HERE.parent / "variant_study"; ROOT = HERE.parent; sys.path.insert(0, str(STUDY))
import grade as g  # noqa: E402
from stack_client import classify_grade, StackAPIError  # noqa: E402
DATA = Path(os.environ.get("PILOT_DATA_DIR", HERE)); POLICY = "raw-v1+brace-off"

def engine_ids():
    out = subprocess.run(["docker", "inspect", "--format", "{{.Name}} {{.Image}}", "stack-api-stack-1", "stack-api-maxima-1"], capture_output=True, text=True)
    return dict(l.strip().lstrip("/").split(" ", 1) for l in out.stdout.strip().splitlines()) if out.returncode == 0 else {}

def main():
    corpus = [ROOT / "not_included/quiz-Math1-Math2.xml", ROOT / "not_included/quiz-Numeric.xml"]
    xml_all = "".join(p.read_text(encoding="utf-8") for p in corpus)
    corpus_sha = {str(p.relative_to(ROOT)): g.file_sha(p) for p in corpus}
    inst = {}
    for line in (DATA / "instances.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line); inst[(r["rc_id"], r["seed"])] = r
    answers = {}
    for line in (DATA / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["status"] != "transport_failure": answers[(r["rc_id"], r["seed"], r["rep"], r["model"])] = r
    res_path = DATA / "results.csv"; done = {}
    if res_path.exists():
        for r in csv.DictReader(open(res_path, encoding="utf-8")): done[(r["rc_id"], int(r["seed"]), int(r["rep"]), r["model"])] = r
    grader_commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    code_sha = g.file_sha(STUDY / "grade.py"); client_sha = g.file_sha(STUDY / "stack_client.py"); corpus_cell = json.dumps(corpus_sha, sort_keys=True)
    frag_cache, tex_cache, rows = {}, {}, []
    for i, (key, a) in enumerate(sorted(answers.items()), 1):
        rc, seed, rep, model = key; a_sha = g.record_sha(a); c = done.get(key)
        if c and c.get("answer_record_sha256") == a_sha and c.get("grader_code_sha256") == code_sha and c.get("corpus_sha256") == corpus_cell and c.get("grading_policy") == POLICY:
            rows.append(c); continue
        ins = inst[(rc, seed)]; frag_cache.setdefault(rc, g.frag_of(xml_all, rc)); ans = a.get("answer")
        if a["status"] in ("format_failure", "empty"):
            status, score, sy, mv, st = a["status"], "", "", "", ""
        else:
            try: raw = g.grade(frag_cache[rc], seed, {ins["input_name"]: ans})
            except StackAPIError as e: print(f"  transport error, rerun later: {e}", flush=True); continue
            status = classify_grade(raw, ans); score = raw["score"]; ta = ins["teacher_answer"]
            sy = g._timed(g._sympy_worker, g.tr(ans), g.tr(ta))
            for t in (ans, ta):
                if t not in tex_cache: tex_cache[t] = g._timed_one(g._latex_worker, g.tr(t))
            mv = g._timed(g._mv_worker, tex_cache[ans], tex_cache[ta]) if tex_cache[ans] is not None and tex_cache[ta] is not None else None
            st = int(g.norm(ans) == g.norm(ta)); sy = "" if sy is None else int(sy); mv = "" if mv is None else int(mv)
        rows.append({"rc_id": rc, "seed": seed, "rep": rep, "model": model, "kind": a["kind"], "answer": ans or "", "status": status, "score": score,
                     "grading_policy": POLICY, "brace_normalized": 0, "sympy_eq": sy, "math_verify_eq": mv, "string_eq": st,
                     "answer_record_sha256": a_sha, "grader_commit": grader_commit, "grader_code_sha256": code_sha,
                     "stack_client_sha256": client_sha, "corpus_sha256": corpus_cell})
        if i % 40 == 0: print(f"  graded {i}/{len(answers)}", flush=True)
    rows.sort(key=lambda r: (r["model"], r["rc_id"], int(r["seed"])))
    with res_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    dis = []
    for r in rows:
        if r["status"] not in ("correct", "wrong", "partial"): continue
        ok = r["status"] == "correct"
        for arm, f in (("sympy", "sympy_eq"), ("math_verify", "math_verify_eq"), ("string", "string_eq")):
            v = g.bool_cell(r[f])
            if v is not None and v != ok:
                dis.append({**r, "arm": arm, "stack_ok": ok, "teacher": inst[(r["rc_id"], int(r["seed"]))]["teacher_answer"]}); break
    with (DATA / "disagreements.jsonl").open("w", encoding="utf-8") as fh:
        for d in dis: fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    man = {"grading_policy": POLICY, "rows": len(rows), "answers": len(answers), "grader_commit": grader_commit, "grader_code_sha256": code_sha,
           "stack_client_sha256": client_sha, "corpus_sha256": corpus_sha, "engine_image_ids": engine_ids(),
           "sha256": {"answers.jsonl": g.file_sha(DATA / "answers.jsonl"), "instances.jsonl": g.file_sha(DATA / "instances.jsonl"), "results.csv": g.file_sha(res_path)}}
    (DATA / "grade_manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    print(f"graded rows: {len(rows)} of {len(answers)} answers -> results.csv | disagreements: {len(dis)}")

if __name__ == "__main__": main()
