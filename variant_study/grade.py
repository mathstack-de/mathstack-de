#!/usr/bin/env python3
"""Randomized-instance study: grade collected answers (PROTOCOL_frozen.md §6),
four arms.

Authoritative: STACK /grade on the pinned container at the SAME injected seed
the model saw. Secondary (logged, never authoritative): SymPy, Math-Verify,
normalized string — all vs the gated structured teacher answer.

Fail-closed: writes results.csv always, but the summary is emitted ONLY when
the grid is complete for every model requested (PROTOCOL §7); otherwise it
prints the holes and exits 1. Conflicting checker rows -> disagreements.jsonl.
"""
import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
LEGACY_DATA = Path(os.environ.get("STUDY_DATA_DIR", HERE))
INPUT_DATA = Path(os.environ.get("STUDY_INPUT_DIR", LEGACY_DATA))
OUTPUT_DATA = Path(os.environ.get("STUDY_OUTPUT_DIR", LEGACY_DATA))
sys.path.insert(0, str(HERE))
from stack_client import grade, classify_grade, StackAPIError  # noqa: E402
import run as run_harness  # noqa: E402
from run import load_grid  # noqa: E402

ROOT = HERE.parent.parent.parent
TRANSLATE = [("%pi", "pi"), ("%e", "E"), ("%i", "I"), ("^", "**")]


def frag_of(xml_all, rc):
    m = re.search(rf'<question type="stack">(?:(?!</question>).)*?'
                  rf'<idnumber>{rc}</idnumber>.*?</question>', xml_all, re.S)
    if not m:
        raise RuntimeError(f"canonical STACK XML block not found for {rc}")
    return m.group(0)


ASCII_EXPR = re.compile(r"^[A-Za-z0-9\s+\-*/^().,%]*\Z")
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*")
DECIMAL = re.compile(
    r"(?<![A-Za-z0-9.])(?:\d+\.\d*|\.\d+)(?:[eE][+\-]?\d+)?"
    r"(?=$|[\s+\-*/^(),%])"
)
SAFE_CALLS = {
    "sqrt", "sin", "cos", "tan", "asin", "acos", "atan",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
    "asinh", "acosh", "atanh", "exp", "log", "ln", "abs", "Abs",
    "floor", "ceiling", "float", "degrees", "round",
}
SAFE_CONSTANTS = {"pi", "E", "I"}
PARSER_INTERNALS = {"Integer", "Float", "Rational", "Symbol", "Function"}


def _safe_sympify(text):
    """Parse a deliberately small Maxima-like scalar-expression grammar.

    ``parse_expr`` evaluates transformed Python code internally, so its
    ``global_dict`` is not a security boundary on its own.  The source is
    therefore rejected before parsing unless it is ASCII arithmetic with no
    attribute-access dot, no underscore, and no calls outside SAFE_CALLS.
    Every remaining bare identifier is supplied as an inert Symbol.  Parsing
    still runs in a time-limited child process; this is an allowlisted
    conversion bridge, not an operating-system sandbox.
    """
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        parse_expr, standard_transformations, implicit_multiplication_application)
    if not text or len(text) > 400 or not ASCII_EXPR.fullmatch(text):
        raise ValueError("rejected by ASCII expression grammar")
    # Remove valid decimal literals, then reject every remaining dot.  This
    # permits 1.5, .5, and 5. while rejecting x.real and 1.__class__.
    if "." in DECIMAL.sub("", text):
        raise ValueError("attribute access or malformed decimal is forbidden")
    identifiers = list(IDENTIFIER.finditer(text))
    local_dict = {}
    for match in identifiers:
        name = match.group(0)
        tail = text[match.end():].lstrip()
        if name in PARSER_INTERNALS:
            raise ValueError(f"parser-internal name is forbidden: {name}")
        if tail.startswith("("):
            if name not in SAFE_CALLS:
                raise ValueError(f"function call is not allowlisted: {name}")
        elif name not in SAFE_CALLS and name not in SAFE_CONSTANTS:
            local_dict[name] = sp.Symbol(name)
    text = text.replace("^", "**")
    safe_names = {
        "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
        "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
        "asinh": sp.asinh, "acosh": sp.acosh, "atanh": sp.atanh,
        "exp": sp.exp, "log": sp.log, "ln": sp.log, "Abs": sp.Abs,
        "abs": sp.Abs, "pi": sp.pi, "E": sp.E, "I": sp.I,
        "floor": sp.floor, "ceiling": sp.ceiling,
        # Maxima float changes representation, not mathematical value.
        "float": lambda value: value,
        "degrees": lambda value: value * 180 / sp.pi,
        # Keep rounding symbolic rather than approximating its tie convention.
        "round": sp.Function("round"),
        # Required by standard_transformations; forbidden in source above.
        "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    }
    global_dict = {"__builtins__": {}, **safe_names}
    return parse_expr(text, global_dict=global_dict, local_dict=local_dict,
                      transformations=standard_transformations +
                      (implicit_multiplication_application,), evaluate=True)


def _sympy_worker(a, b, q):
    try:
        import sympy as sp
        ea, eb = _safe_sympify(a), _safe_sympify(b)
        q.put(bool(sp.simplify(ea - eb) == 0))
    except Exception:
        q.put(None)


def _mv_worker(a, b, q):
    try:
        from math_verify import parse, verify
        from math_verify.parser import LatexExtractionConfig
        cfg = [LatexExtractionConfig()]
        gold = parse(f"${b}$", extraction_config=cfg)
        answer = parse(f"${a}$", extraction_config=cfg)
        q.put(bool(gold and answer and verify(gold, answer)))
    except Exception:
        q.put(None)


def _latex_worker(expr, q):
    """Parse inert text with SymPy and emit LaTeX; never execute model text."""
    try:
        import sympy as sp
        q.put(sp.latex(_safe_sympify(expr)))
    except Exception:
        q.put(None)


def _timed(worker, a, b, timeout=30):
    q = mp.Queue()
    p = mp.Process(target=worker, args=(a, b, q))
    p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join()
        return None
    return q.get() if not q.empty() else None


def _timed_one(worker, value, timeout=30):
    q = mp.Queue()
    p = mp.Process(target=worker, args=(value, q))
    p.start(); p.join(timeout)
    if p.is_alive():
        p.terminate(); p.join()
        return None
    return q.get() if not q.empty() else None


def tr(s):
    for x, y in TRANSLATE:
        s = s.replace(x, y)
    return s


def norm(s):
    return re.sub(r"\s+", "", s or "").lower()


def record_sha(row):
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_clean_sources(paths):
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *map(str, paths)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        sys.exit("REFUSING grading: grader, protocol, profile, or corpus sources "
                 f"are dirty:\n{dirty}")


def strip_redundant_outer_brace(s):
    """If `s` is entirely enclosed in ONE matching {...} pair (bracket depth
    returns to 0 only at the final character, never before), return the
    stripped inner text. Otherwise None. Guards against unsafe stripping of
    strings that only superficially start with { and end with } (e.g.
    "{a}+{b}") by requiring the opening brace's own matching close to be the
    last character."""
    if len(s) < 2 or s[0] != "{" or s[-1] != "}":
        return None
    depth = 0
    for i, ch in enumerate(s):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and i != len(s) - 1:
                return None
    return s[1:-1] if depth == 0 else None


def bool_cell(value):
    if value in (1, "1", True):
        return True
    if value in (0, "0", False):
        return False
    return None


def grade_with_policy(question_xml, seed, input_name, answer, policy):
    """Return raw/final STACK outcomes plus a complete normalization trace."""
    raw = grade(question_xml, seed, {input_name: answer})
    raw_status = classify_grade(raw, answer)
    trace = [{
        "layers_stripped": 0,
        "candidate": answer,
        "isgradable": bool(raw.get("isgradable")),
        "score": raw.get("score"),
        "status": raw_status,
    }]
    best = raw
    best_answer = answer
    best_layers = 0
    if policy == "outer" and raw.get("isgradable") and raw.get("score") != 1:
        candidate = answer
        for layers in range(1, 4):
            candidate = strip_redundant_outer_brace(candidate)
            if candidate is None:
                break
            retried = grade(question_xml, seed, {input_name: candidate})
            retried_status = classify_grade(retried, candidate)
            trace.append({
                "layers_stripped": layers,
                "candidate": candidate,
                "isgradable": bool(retried.get("isgradable")),
                "score": retried.get("score"),
                "status": retried_status,
            })
            if (retried.get("isgradable")
                    and (retried.get("score") or 0) > (best.get("score") or 0)):
                best = retried
                best_answer = candidate
                best_layers = layers
                if retried.get("score") == 1:
                    break
    return raw, best, best_answer, best_layers, trace


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--brace-normalization", choices=("off", "outer"), default="off",
        help=("grading policy: raw answer as submitted (off, default), or the "
              "post-hoc outer-brace sensitivity policy (outer)"),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    grading_policy = f"raw-v1+brace-{args.brace_normalization}"
    OUTPUT_DATA.mkdir(parents=True, exist_ok=True)
    corpus_paths = [ROOT / "not_included/quiz-Math1-Math2.xml",
                    ROOT / "not_included/quiz-Numeric.xml"]
    source_paths = [HERE / "grade.py", HERE / "stack_client.py", HERE / "run.py",
                    HERE / "PROTOCOL.md", HERE / "profiles.json",
                    HERE / "probes_report.json", HERE / "profile_probes.json",
                    INPUT_DATA / "model_roster.json", *corpus_paths]
    require_clean_sources(source_paths)
    corpus_sha256 = {str(path.relative_to(ROOT)): file_sha(path) for path in corpus_paths}
    xml_all = "".join(path.read_text(encoding="utf-8") for path in corpus_paths)
    inst = {}
    for line in (INPUT_DATA / "instances.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        inst[(r["rc_id"], r["seed"])] = r
    all_answers = {}
    for line in (INPUT_DATA / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["status"] != "transport_failure":
            all_answers[(r["rc_id"], r["seed"], r["rep"], r["model"])] = r

    draw = json.loads((INPUT_DATA / "draw_log.json").read_text(encoding="utf-8"))
    for rel, expected in draw.get("input_sha256", {}).items():
        path = ROOT / rel
        if not path.exists() or file_sha(path) != expected:
            sys.exit(f"frozen draw input changed or disappeared: {rel}")
    profiles = json.loads((HERE / "profiles.json").read_text(encoding="utf-8"))["models"]
    profile_by_model = {profile["id"]: profile for profile in profiles}
    roster_path = INPUT_DATA / "model_roster.json"
    if not roster_path.exists():
        sys.exit("model_roster.json missing — finalize and freeze kill gates first")
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    if roster.get("profiles_sha256") != run_harness.PROFILE_SHA256:
        sys.exit("model roster targets another profiles.json")
    models = roster.get("retained_models", [])
    dropped_models = roster.get("dropped_models", [])
    if not models or set(models + dropped_models) != set(profile_by_model):
        sys.exit("model roster is empty or does not partition the five frozen profiles")
    _, _, grid = load_grid()
    if draw.get("rows_per_model") != len(grid):
        sys.exit("draw_log rows_per_model disagrees with reconstructed frozen grid")
    expected_grid = {(rc, seed, rep, model)
                     for model in models for rc, seed, _kind, rep in grid}
    selection = list(csv.DictReader(open(INPUT_DATA / "selection.csv", encoding="utf-8")))
    first15 = {row["rc_id"] for row in selection[:15]}
    kill_grid = [key for key in grid if key[0] in first15 and key[3] == 0]
    allowed_dropped = {(rc, seed, rep, model) for model in dropped_models
                       for rc, seed, _kind, rep in kill_grid}
    unexpected_answers = set(all_answers) - expected_grid - allowed_dropped
    if unexpected_answers:
        sys.exit(f"answers contain {len(unexpected_answers)} keys outside frozen grid")
    probes_sha256 = file_sha(run_harness.PROBES_PATH)
    profile_probes_sha256 = file_sha(run_harness.PROFILE_PROBES_PATH)
    probes = json.loads(run_harness.PROBES_PATH.read_text(encoding="utf-8"))
    engine_digests = probes["probes"]["P6_environment"]["image_digests"]
    try:
        run_harness.validate_resumed_records(
            all_answers, inst, profiles, probes_sha256, profile_probes_sha256,
            engine_digests,
        )
    except RuntimeError as exc:
        sys.exit(f"answer provenance invalid: {exc}")
    answers = {key: row for key, row in all_answers.items() if key in expected_grid}

    # Exact response-grid completeness; a matching row count is insufficient.
    holes = {}
    for m in models:
        wanted = {key for key in expected_grid if key[3] == m}
        missing = wanted - set(answers)
        if missing:
            holes[m] = {"have": len(wanted) - len(missing),
                        "expected": len(wanted),
                        "missing_examples": [list(key) for key in sorted(missing)[:5]]}
    frag_cache = {}
    rows, disagreements = [], []
    done_grades = {}
    res_path = OUTPUT_DATA / "results.csv"
    (OUTPUT_DATA / "grade_manifest.json").unlink(missing_ok=True)
    if res_path.exists():
        for r in csv.DictReader(open(res_path, encoding="utf-8")):
            done_grades[(r["rc_id"], int(r["seed"]), int(r["rep"]), r["model"])] = r

    grader_commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    grader_code_sha256 = file_sha(HERE / "grade.py")
    stack_client_sha256 = file_sha(HERE / "stack_client.py")
    corpus_sha_cell = json.dumps(corpus_sha256, sort_keys=True)
    tex_cache = {}

    for i, (key, a) in enumerate(sorted(answers.items()), 1):
        rc, seed, rep, model = key
        a_sha = record_sha(a)
        cached = done_grades.get(key)
        if (cached and cached.get("answer_record_sha256") == a_sha
                and cached.get("grader_commit") == grader_commit
                and cached.get("grader_code_sha256") == grader_code_sha256
                and cached.get("stack_client_sha256") == stack_client_sha256
                and cached.get("corpus_sha256") == corpus_sha_cell
                and cached.get("grading_policy") == grading_policy):
            rows.append(cached)
            continue
        ins = inst[(rc, seed)]
        if rc not in frag_cache:
            frag_cache[rc] = frag_of(xml_all, rc)
        ans = a.get("answer")
        if a["status"] in ("format_failure", "empty"):
            status, sy, mv, st, score = a["status"], "", "", "", ""
            raw_status, raw_score = status, score
            normalized_answer, brace_layers, retry_trace = "", 0, []
        else:
            try:
                raw_g, g, final_answer, brace_layers, retry_trace = grade_with_policy(
                    frag_cache[rc], seed, ins["input_name"], ans,
                    args.brace_normalization,
                )
            except StackAPIError as e:
                print(f"  grade transport error (rerun later): {e}", flush=True)
                continue
            raw_status = classify_grade(raw_g, ans)
            raw_score = raw_g["score"]
            status = classify_grade(g, final_answer)
            score = g["score"]
            normalized_answer = final_answer if brace_layers else ""
            ta = ins["teacher_answer"]
            sy = _timed(_sympy_worker, tr(ans), tr(ta))
            if ans not in tex_cache:
                tex_cache[ans] = _timed_one(_latex_worker, tr(ans))
            if ta not in tex_cache:
                tex_cache[ta] = _timed_one(_latex_worker, tr(ta))
            tex_ans, tex_ta = tex_cache[ans], tex_cache[ta]
            mv = (_timed(_mv_worker, tex_ans, tex_ta)
                  if tex_ans is not None and tex_ta is not None else None)
            st = norm(ans) == norm(ta)
            sy = "" if sy is None else int(sy)
            mv = "" if mv is None else int(mv)
            st = int(st)
        row = {"rc_id": rc, "seed": seed, "rep": rep, "model": model,
               "kind": a["kind"], "answer": ans or "",
               "raw_status": raw_status, "raw_score": raw_score,
               "status": status, "score": score,
               "grading_policy": grading_policy,
               "brace_normalized": int(brace_layers > 0),
               "brace_layers_stripped": brace_layers,
               "normalized_answer": normalized_answer,
               "brace_retry_trace_json": json.dumps(
                   retry_trace, ensure_ascii=False, separators=(",", ":")
               ),
               "sympy_eq": sy, "math_verify_eq": mv, "string_eq": st,
               "answer_record_sha256": a_sha, "grader_commit": grader_commit,
               "grader_code_sha256": grader_code_sha256,
               "stack_client_sha256": stack_client_sha256,
               "corpus_sha256": corpus_sha_cell}
        rows.append(row)
        if i % 50 == 0:
            print(f"  graded {i}/{len(answers)}", flush=True)

    if not rows:
        print("GRID INCOMPLETE — no gradeable response rows")
        sys.exit(1)
    rows.sort(key=lambda row: (row["model"], row["rc_id"], int(row["seed"]),
                               int(row["rep"])))
    with res_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # Rebuild disagreements from every row, including safely reused checkpoints.
    for row in rows:
        if row["status"] not in ("correct", "wrong", "partial"):
            continue
        stack_ok = row["status"] == "correct"
        for arm, field in (("sympy", "sympy_eq"),
                           ("math_verify", "math_verify_eq"),
                           ("string", "string_eq")):
            verdict = bool_cell(row[field])
            if verdict is not None and verdict != stack_ok:
                disagreements.append({**row, "arm": arm, "stack_ok": stack_ok,
                                      "teacher": inst[(row["rc_id"], int(row["seed"]))]
                                      ["teacher_answer"]})
                break
    with (OUTPUT_DATA / "disagreements.jsonl").open("w", encoding="utf-8") as fh:
        for d in disagreements:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"graded rows: {len(rows)} -> results.csv | "
          f"checker disagreements: {len(disagreements)}")

    result_keys = {(row["rc_id"], int(row["seed"]), int(row["rep"]), row["model"])
                   for row in rows}
    grade_holes = expected_grid - result_keys
    if grade_holes:
        holes["grading"] = {"have": len(result_keys & expected_grid),
                            "expected": len(expected_grid),
                            "missing_examples": [list(key)
                                                 for key in sorted(grade_holes)[:5]]}
    if holes:
        print("\nGRID INCOMPLETE — no summary (PROTOCOL §7). Holes:")
        for m, h in holes.items():
            print(f"  {m}: {h}")
        sys.exit(1)

    grade_manifest = {
        "rows": len(rows),
        "models": models,
        "rows_per_model": len(grid),
        "grader_commit": grader_commit,
        "retained_models": models,
        "dropped_models": dropped_models,
        "grading_policy": grading_policy,
        "brace_normalization": args.brace_normalization,
        "symbolic_bridge_policy": (
            "ASCII arithmetic grammar + call/attribute allowlist, parsed in a "
            "time-limited child process; not an OS sandbox"
        ),
        "math_verify_input": "LaTeX from the allowlisted Maxima-to-SymPy bridge",
        "producer_commits": sorted({row.get("harness_commit")
                                     for row in answers.values()
                                     if row.get("harness_commit")}),
        "sha256": {
            "answers": file_sha(INPUT_DATA / "answers.jsonl"),
            "instances": file_sha(INPUT_DATA / "instances.jsonl"),
            "draw_log": file_sha(INPUT_DATA / "draw_log.json"),
            "selection": file_sha(INPUT_DATA / "selection.csv"),
            "model_roster": file_sha(roster_path),
            "profiles": file_sha(HERE / "profiles.json"),
            "profile_probes": profile_probes_sha256,
            "preflight_probes": probes_sha256,
            "protocol": file_sha(HERE / "PROTOCOL.md"),
            "grader": file_sha(HERE / "grade.py"),
            "stack_client": stack_client_sha256,
            **corpus_sha256,
            "results": file_sha(res_path),
            "disagreements": file_sha(OUTPUT_DATA / "disagreements.jsonl"),
        },
    }
    (OUTPUT_DATA / "grade_manifest.json").write_text(
        json.dumps(grade_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("\n=== summary (fresh arm, rep 0; STACK authoritative) ===")
    for m in models:
        sub = [r for r in rows if r["model"] == m and r["kind"] == "fresh"
               and int(r["rep"]) == 0]
        anc = [r for r in rows if r["model"] == m and r["kind"] == "anchor"]
        acc = sum(1 for r in sub if r["status"] == "correct")
        aacc = sum(1 for r in anc if r["status"] == "correct")
        byt = defaultdict(list)
        for r in sub:
            byt[r["rc_id"]].append(r["status"] == "correct")
        full = sum(1 for v in byt.values() if all(v))
        none = sum(1 for v in byt.values() if not any(v))
        part = len(byt) - full - none
        fmt = Counter(r["status"] for r in rows if r["model"] == m)
        print(f"  {m[:34]:34} fresh {acc}/{len(sub)}  anchor {aacc}/{len(anc)}  "
              f"consistency {full}/{part}/{none}  statuses {dict(fmt)}")


if __name__ == "__main__":
    main()
