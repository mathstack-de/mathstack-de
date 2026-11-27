#!/usr/bin/env python3
"""Build the paired solving views: one validated seed-42
reference variant per auto-gradable STACK question, rendered and round-tripped
against the pinned local STACK API.

``solving_public`` carries the learner-visible task only. ``solving_with_keys``
adds the seed-evaluated teacher answers, the instantiated worked solution, and
the item's grading source (question variables and PRTs), so the two views are
the release's answer-free/key-bearing pair. Both contain identical
``variant_id`` sets and identical rendered question text.

Sealed field: the API's ``questionnote`` may contain the answer and is never
written to either view or the manifest.

Requires the pinned containers (stackmaths/stackapi:2026042200,
mathinstitut/goemaxima:2026042200) behind http://127.0.0.1:3080. Fails closed
on any render failure; round-trip failures are recorded per row, not fatal.
"""
import argparse
import hashlib
import html as html_mod
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
CORPUS = [ROOT / "not_included/quiz-Math1-Math2.xml", ROOT / "not_included/quiz-Numeric.xml"]

API_BASE = "http://127.0.0.1:3080"
TIMEOUT = 90
REFERENCE_SEED = 42
SCHEMA_VERSION = "solving_v2"

Q_RE = re.compile(r'<question type="stack">.*?</question>', re.S)
ID_RE = re.compile(r"<idnumber>(rc-[0-9a-f-]{36})</idnumber>")
OPTION_INPUT_TYPES = {"dropdown", "checkbox", "radio"}

PUBLIC_COLUMNS = [
    "dataset_version", "schema_version", "variant_id", "rc_id", "seed",
    "seed_origin", "is_author_deployed", "question_text_rendered",
    "answer_options_rendered", "response_schema_json",
    "instantiation_status", "engine_build", "render_sha256",
]
KEY_COLUMNS = PUBLIC_COLUMNS + [
    "expected_responses", "generalfeedback_rendered", "questionvariables",
    "stack_prts_json", "roundtrip_score", "roundtrip_ok", "roundtrip_form",
]


class StackAPIError(RuntimeError):
    pass


def post(route, payload, retries=3):
    last = None
    for attempt in range(retries):
        try:
            r = requests.post(f"{API_BASE}{route}", json=payload,
                              timeout=TIMEOUT)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 503):
            last = f"HTTP {r.status_code}"
            time.sleep(10 * (attempt + 1))
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            raise StackAPIError(
                f"{route}: non-JSON response {r.status_code}: {r.text[:200]}")
    raise StackAPIError(f"{route}: transport failure after {retries} tries "
                        f"({last})")


def inject_seed(question_xml, seed):
    if f"<deployedseed>{seed}</deployedseed>" in question_xml:
        return question_xml
    return question_xml.replace(
        "</question>", f"<deployedseed>{seed}</deployedseed>\n</question>")


def strip_html_keep_math(s):
    s = re.sub(r"\[\[input:([^\]]+)\]\]", " ___ ", s)
    s = re.sub(r"\[\[validation:[^\]]+\]\]", " ", s)
    s = re.sub(r"<input[^>]*>", " ___ ", s)
    s = re.sub(r"<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()


def render(question_xml, seed):
    """Returns (raw response, canonical teacher values, grade payload).

    ``samplesolution`` is a mapping whose keys are form-field suffixes: ``""``
    for scalar inputs, ``_sub_r_c`` for matrix cells, and ``_val`` for the
    assembled display value (not a form field). The canonical value per input
    is the assembled ``_val`` when present, else the scalar; the grade payload
    submits every real form field.
    """
    status, d = post("/render", {
        "questionDefinition": f"<quiz>{inject_seed(question_xml, seed)}</quiz>",
        "seed": seed,
    })
    if status != 200 or "questionrender" not in d:
        raise StackAPIError(f"render s={seed}: HTTP {status} "
                            f"{json.dumps(d, ensure_ascii=False)[:200]}")
    teacher = {}
    payload = {}
    for name, info in (d.get("questioninputs") or {}).items():
        sol = info.get("samplesolution")
        if isinstance(sol, dict):
            if "_val" in sol:
                teacher[name] = sol["_val"]
            elif "" in sol:
                teacher[name] = sol[""]
            else:
                # option/matrix inputs with per-field solutions only: the
                # sub-field mapping is the canonical teacher value
                teacher[name] = {k: str(v) for k, v in sol.items()
                                 if v is not None}
            for key, value in sol.items():
                if key == "_val" or value is None:
                    continue
                payload[name + key] = str(value)
        elif sol is not None:
            teacher[name] = str(sol)
            payload[name] = str(sol)
    return d, teacher, payload


def grade(question_xml, seed, answers):
    status, d = post("/grade", {
        "questionDefinition": f"<quiz>{inject_seed(question_xml, seed)}</quiz>",
        "seed": seed, "answers": answers,
    })
    if status == 200 and isinstance(d, dict) and "isgradable" in d:
        return d
    raise StackAPIError(f"grade s={seed}: HTTP {status} "
                        f"{json.dumps(d, ensure_ascii=False)[:200]}")


def load_fragments():
    fragments = {}
    for path in CORPUS:
        for match in Q_RE.finditer(path.read_text(encoding="utf-8")):
            fragment = match.group(0)
            id_match = ID_RE.search(fragment)
            if not id_match:
                raise RuntimeError(f"STACK fragment without rc_id in {path}")
            fragments[id_match.group(1)] = fragment
    return fragments


def engine_build_string():
    """Digest-pinned engine identifier from the running containers."""
    parts = []
    for container in ("stack-api-stack-1", "stack-api-maxima-1"):
        try:
            out = subprocess.run(
                ["docker", "inspect", "--format",
                 "{{.Config.Image}}@{{.Image}}", container],
                capture_output=True, text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(
                f"container {container} not inspectable; the pinned "
                "stack-api/goemaxima 2026042200 deployment must be running")
        parts.append(out)
    return ";".join(parts)


def rendered_options(raw, schema_json):
    """Rendered HTML for option-bearing inputs only; null otherwise."""
    try:
        input_types = {i["name"]: i.get("input_type", "")
                       for i in json.loads(schema_json).get("inputs", [])}
    except (ValueError, TypeError):
        input_types = {}
    options = {}
    for name, info in (raw.get("questioninputs") or {}).items():
        if input_types.get(name, "").lower() in OPTION_INPUT_TYPES:
            rendered = info.get("render")
            if rendered:
                options[name] = rendered
    return json.dumps(options, ensure_ascii=False, sort_keys=True) if options \
        else None


def main(limit=None):
    source_path = OUT / "data/source/all-00000-of-00001.parquet"
    source = pq.read_table(source_path).to_pandas()
    source_schema_versions = set(source.schema_version)
    if source_schema_versions != {"source_v2"}:
        sys.exit("build_source.py must produce source_v2 before solving views; "
                 f"found {sorted(source_schema_versions)}")
    stack = source[(source.question_type == "stack")
                   & source.is_auto_gradable].reset_index(drop=True)
    excluded = source[(source.question_type == "stack")
                      & ~source.is_auto_gradable].rc_id.tolist()
    fragments = load_fragments()
    missing = [rc for rc in stack.rc_id if rc not in fragments]
    if missing:
        sys.exit(f"{len(missing)} STACK rc_ids missing XML fragments: "
                 f"{missing[:3]}")

    engine = engine_build_string()
    dataset_version = source.dataset_version.iloc[0]
    if limit:
        stack = stack.head(limit)

    rows = []
    roundtrip_failures = []
    started = time.time()
    for n, row in enumerate(stack.itertuples(), 1):
        fragment = fragments[row.rc_id]
        raw, teacher, payload = render(fragment, REFERENCE_SEED)
        answers = {k: v for k, v in teacher.items() if v is not None}
        grade_error = None
        verdict = None
        roundtrip_form = "as_rendered"
        if payload:
            try:
                verdict = grade(fragment, REFERENCE_SEED, payload)
            except StackAPIError as e:
                # a grading engine error on the item's own teacher answer is
                # a content finding, recorded per row, never a build failure
                grade_error = str(e)[:200]

        def full(v):
            return (v is not None and v.get("isgradable")
                    and v.get("score") is not None
                    and abs(v["score"] - 1.0) < 1e-9)

        # Numerical inputs can reject the API's own "N.0" display form while
        # accepting the identical integer; one exact-value-preserving retry.
        if not full(verdict) and grade_error is None:
            normalized = {k: re.sub(r"^(-?\d+)\.0+$", r"\1", v)
                          for k, v in payload.items()}
            if normalized != payload:
                try:
                    retry = grade(fragment, REFERENCE_SEED, normalized)
                    if full(retry):
                        verdict = retry
                        roundtrip_form = "normalized_number"
                except StackAPIError as e:
                    grade_error = str(e)[:200]
        score = None if verdict is None else verdict.get("score")
        roundtrip_ok = full(verdict)
        if not roundtrip_ok:
            summary = None if verdict is None else \
                str(verdict.get("responsesummary"))[:160]
            roundtrip_failures.append(
                {"rc_id": row.rc_id,
                 "reason": grade_error or "score below full credit",
                 "score": score,
                 "responsesummary": summary})

        question_text = strip_html_keep_math(raw["questionrender"])
        solution_text = strip_html_keep_math(
            raw.get("questionsamplesolutiontext") or "") or None
        digest_payload = json.dumps({
            "rc_id": row.rc_id, "seed": REFERENCE_SEED,
            "questionrender": raw["questionrender"],
            "samplesolution": raw.get("questionsamplesolutiontext") or "",
            "teacher": answers,
        }, ensure_ascii=False, sort_keys=True)
        render_sha = hashlib.sha256(digest_payload.encode()).hexdigest()
        seeds = row.deployed_seeds if row.deployed_seeds is not None else []
        deployed = set(int(s) for s in seeds)
        rows.append({
            "dataset_version": dataset_version,
            "schema_version": SCHEMA_VERSION,
            "variant_id": "var-" + hashlib.sha256(
                f"{row.rc_id}|{REFERENCE_SEED}|{engine}".encode()
            ).hexdigest()[:16],
            "rc_id": row.rc_id,
            "seed": REFERENCE_SEED,
            "seed_origin": ("author_deployed" if REFERENCE_SEED in deployed
                            else "reference_generated"),
            "is_author_deployed": REFERENCE_SEED in deployed,
            "question_text_rendered": question_text,
            "answer_options_rendered": rendered_options(
                raw, row.response_schema_json),
            "response_schema_json": row.response_schema_json,
            "instantiation_status": "ok",
            "engine_build": engine,
            "render_sha256": render_sha,
            "expected_responses": json.dumps(
                answers, ensure_ascii=False, sort_keys=True),
            "generalfeedback_rendered": solution_text,
            "questionvariables": row.questionvariables,
            "stack_prts_json": row.stack_prts_json,
            "roundtrip_score": None if score is None else float(score),
            "roundtrip_ok": bool(roundtrip_ok),
            "roundtrip_form": roundtrip_form,
        })
        if n % 100 == 0:
            rate = n / (time.time() - started)
            print(f"  {n}/{len(stack)} rendered "
                  f"({rate:.1f}/s, {len(roundtrip_failures)} roundtrip "
                  "failures)", flush=True)

    frame = pd.DataFrame(rows)
    if frame.rc_id.duplicated().any() or frame.variant_id.duplicated().any():
        sys.exit("duplicate rc_id or variant_id in variant rows")

    for name, columns in (("solving_public", PUBLIC_COLUMNS),
                          ("solving_with_keys", KEY_COLUMNS)):
        directory = OUT / "data" / name
        directory.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pandas(frame[columns], preserve_index=False),
            directory / "all-00000-of-00001.parquet")
        print(f"wrote {name}: {len(frame)} rows x {len(columns)} cols")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "reference_seed": REFERENCE_SEED,
        "engine_build": engine,
        "api_base": API_BASE,
        "source_schema_version": "source_v2",
        "source_table_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_xml_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in CORPUS},
        "rows": len(frame),
        "excluded_non_gradable": excluded,
        "seed_origin_counts":
            frame.seed_origin.value_counts().to_dict(),
        "roundtrip_full_credit": int(frame.roundtrip_ok.sum()),
        "roundtrip_failures": roundtrip_failures,
        "roundtrip_grade_errors": sum(
            1 for f in roundtrip_failures
            if "score below" not in f["reason"]),
        "sealed_fields_excluded": ["questionnote"],
        "views": {
            "solving_public": PUBLIC_COLUMNS,
            "solving_with_keys": KEY_COLUMNS,
        },
    }
    (OUT / "manifests").mkdir(exist_ok=True)
    (OUT / "manifests/solving_build_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"manifest written; roundtrip full credit "
          f"{manifest['roundtrip_full_credit']}/{len(frame)}")
    if roundtrip_failures:
        print(f"NOTE: {len(roundtrip_failures)} teacher answers did not "
              "round-trip to full credit at the reference seed; they remain "
              "in the views with roundtrip_ok=false")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="build only the first N rows (smoke test)")
    main(limit=parser.parse_args().limit)
