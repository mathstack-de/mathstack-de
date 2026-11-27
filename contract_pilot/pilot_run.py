#!/usr/bin/env python3
"""Contract pilot — collect model answers over the frozen 20x4 grid (PROTOCOL §4).
Reuses the collection script of the main study (run.py, not included) unchanged for
prompts, extraction, Ollama calls and digests.
Env: OLLAMA_URL (Ollama endpoint), PILOT_DATA_DIR (default: this directory)."""
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
HERE = Path(__file__).parent; STUDY = HERE.parent / "variant_study"; sys.path.insert(0, str(STUDY))
import run as rh  # noqa: E402
DATA = Path(os.environ.get("PILOT_DATA_DIR", HERE))
LOCAL = ["gemma4:31b", "qwen3:32b", "hf.co/unsloth/GLM-4-32B-0414-GGUF:Q4_K_M", "hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M"]
ALL = ["gpt-5-2025-08-07"] + LOCAL
FROZEN = ["PROTOCOL.md", "pilot_run.py", "select_pilot.py", "pilot_grade.py", "analyze_pilot.py", "selection.csv", "instances.jsonl", "draw_log.json",
          "inputs/gated_pool.jsonl", "inputs/gated_pool_coverage.jsonl", "inputs/candidates.csv", "inputs/gate_pool.py"]

def verify_frozen(allow_dirty):
    man_path = HERE / "frozen_manifest.json"
    if not man_path.exists(): sys.exit("REFUSING to run: frozen_manifest.json missing (run freeze.py after the draw)")
    man = json.loads(man_path.read_text(encoding="utf-8"))
    for name, want in man["sha256"].items():
        p = HERE / name
        got = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        if got != want and not allow_dirty: sys.exit(f"REFUSING to run: frozen file changed since freeze: {name}")
    if (STUDY / "run.py").exists():
        for name in ("run.py", "profiles.json"):
            got = hashlib.sha256((STUDY / name).read_bytes()).hexdigest()
            if got != man["harness_sha256"][name] and not allow_dirty: sys.exit(f"REFUSING to run: harness file changed since freeze: {name}")
    return man
JULY_DIGESTS = {"gemma4:31b": "6316f0629137b426", "qwen3:32b": "e1c9f234c6eb3754",
                "hf.co/unsloth/GLM-4-32B-0414-GGUF:Q4_K_M": "ecb6d68a29d28994", "hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M": "1a940a9f854a7108"}

def load_grid():
    import csv
    sel = list(csv.DictReader(open(DATA / "selection.csv", encoding="utf-8")))
    inst = {}
    for line in (DATA / "instances.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line); inst[(r["rc_id"], r["seed"])] = r
    grid = [(row["rc_id"], int(s), "fresh", 0) for row in sel for s in row["fresh_seeds"].split()]
    for rc, seed, _, _ in grid:
        if (rc, seed) not in inst: sys.exit(f"instance missing for {rc} seed {seed}")
    return sel, inst, grid

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--models", default="all"); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--allow-dirty", action="store_true"); ap.add_argument("--grid", action="store_true"); args = ap.parse_args()
    sel, inst, grid = load_grid()
    if args.grid:
        print(f"grid: {len(sel)} questions x 4 instances = {len(grid)} per model; {len(grid)*len(ALL)} total"); return
    man = verify_frozen(args.allow_dirty); commit = man["commit"]
    wanted = [p for p in rh.PROFILES if p["id"] in ALL and (args.models == "all" or p["id"] in args.models.split(","))]
    if not wanted: sys.exit("no profile selected")
    if any(p["provider"] == "openai" for p in wanted) and not os.environ.get("OPENAI_API_KEY"): sys.exit("REFUSING: OPENAI_API_KEY not set for the GPT-5 profile")
    protocol_sha = hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest()
    ans_path = DATA / "answers.jsonl"; rh.init_answer_log(ans_path)
    done = {}
    if ans_path.exists():
        for line in ans_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["status"] != "transport_failure": done[(r["rc_id"], r["seed"], r["rep"], r["model"])] = r
    for profile in wanted:
        m = profile["id"]
        if profile["provider"] == "ollama":
            try: dig = rh.model_digest(m)
            except Exception as exc: sys.exit(f"REFUSING calls: model provenance unresolved for {m}: {exc}")
            old = {r["model_digest"]["digest"] for r in done.values() if r["model"] == m}
            if old and old != {dig["digest"]}: sys.exit(f"REFUSING checkpoint reuse: served digest changed for {m}")
            same = dig["digest"].startswith(JULY_DIGESTS[m])
            print(f"[{m}] served digest {dig['digest'][:16]} — {'SAME as July' if same else 'DIFFERS from July ' + JULY_DIGESTS[m] + ' (documented deviation)'}", flush=True)
        else:
            dig, same = {"snapshot": m}, True
            print(f"[{m}] snapshot-pinned API profile", flush=True)
        todo = [k for k in grid if (k[0], k[1], k[3], m) not in done]
        if args.limit: todo = todo[:args.limit]
        print(f"[{m}] {len(todo)} calls pending", flush=True)
        for i, (rc, seed, kind, rep) in enumerate(todo, 1):
            ins = inst[(rc, seed)]
            user = rh.USER_TMPL.format(qt=ins["prompt_text"], input_name=ins["input_name"])
            out = rh.call_ollama(profile, user) if profile["provider"] == "ollama" else rh.call_openai(profile, user)
            if out is None:
                status, ans = "transport_failure", None
                out = {"content": "", "thinking": "", "done_reason": None, "response_model": None, "system_fingerprint": None,
                       "request_id": None, "prompt_tokens": None, "output_tokens": None, "latency_s": None}
            else:
                ans = rh.extract(out["content"] or "")
                status = "ok" if ans else ("empty" if not (out["content"] or out["thinking"]).strip() else "format_failure")
            rec = {"rc_id": rc, "seed": seed, "kind": kind, "rep": rep, "model": m, "provider": profile["provider"], "answer": ans, "status": status,
                   "prompt_sha256": rh.request_prompt_sha256(profile, user), "instance_prompt_sha256": ins["prompt_sha256"],
                   "options": profile["options"], "model_digest": dig, "july_digest_prefix": JULY_DIGESTS.get(m, ""), "same_build_as_july": same,
                   "harness_commit": commit, "profiles_sha256": rh.PROFILE_SHA256, "pilot_protocol_sha256": protocol_sha,
                   "raw_content": out["content"], "thinking": out["thinking"], "response_model": out["response_model"],
                   "system_fingerprint": out["system_fingerprint"], "request_id": out["request_id"], "done_reason": out["done_reason"],
                   "prompt_tokens": out["prompt_tokens"], "output_tokens": out["output_tokens"], "latency_s": out["latency_s"],
                   "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            rh.append_record(ans_path, rec)
            print(f"[{m} {i}/{len(todo)}] {ins['name'][:34]:34} s={seed} -> {status:15} {(ans or '')[:40]}", flush=True)
            if status != "transport_failure": done[(rc, seed, rep, m)] = rec
    print("collection pass complete", flush=True)

if __name__ == "__main__": main()
