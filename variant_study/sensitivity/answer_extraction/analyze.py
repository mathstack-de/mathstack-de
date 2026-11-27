#!/usr/bin/env python3
"""Regrade malformed-wrapper GLM-Z1 responses under frozen STACK semantics."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = ROOT / "variant_study"
PRIMARY = DATA
MODEL = "hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M"
BOOTSTRAPS = 2000
BOOTSTRAP_SEED = 20260808

# The hashes of the inputs as the audit read them; several of these files
# were edited for publication since, so the check holds for them as run.
EXPECTED_HASHES = {
    DATA / "answers.jsonl":
        "973558822c517a7f61e83a3a9b8d1bac305b8e2f541d5717d3fbfc324b943241",
    DATA / "instances.jsonl":
        "26605c2702ecd2c8e232a4ec96b94b00d64e1efd216799f2aea972668e2a5c23",
    PRIMARY / "results.csv":
        "814c0018fe74868291c68ddfccaf0efd23973f458414c105e0e930b0556d55ab",
    PRIMARY / "analysis.json":
        "b31b09aa10be7cca8fad2f81b035983656ba7dfceec963f2507876e9ee7b5fb6",
    PRIMARY / "PROTOCOL_frozen.md":
        "0d85ea655a4f946187bcf2a80f026f1c954b159fc7f0a65ba23e259372335908",
    DATA / "stack_client.py":
        "baee30fa38b2cbb630aeea4a4ad52c6f133f831524149b807f39a61f5356f80f",
}
# The source exports (not included).
CORPUS_HASHES = {
    "not_included/quiz-Math1-Math2.xml":
        "d92c2cc4f694e11c1d41cf1e623512b7598c4151a795ec3520c48a3eb274f597",
    "not_included/quiz-Numeric.xml":
        "cc2c965cfc68b93416598982dc51c1248764cecfe86c4944e568b895f556ada5",
}
IMAGE_IDS = {
    "stack-api-stack-1":
        "sha256:d2ea6572d7ac61013c26297a67940e6b74285139c22f42b4baf36d1d23e446f1",
    "stack-api-maxima-1":
        "sha256:880ce11303726f3b94939cc41baae82ea8ce23a3b308fa3a31d6e4f5d31e8690",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_hashes() -> None:
    for path, expected in EXPECTED_HASHES.items():
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"hash mismatch for {path}: {actual} != {expected}")


def load_frozen_corpus() -> str:
    parts = []
    for path, expected in CORPUS_HASHES.items():
        data = (ROOT / path).read_bytes()
        actual = sha256_bytes(data)
        if actual != expected:
            raise RuntimeError(f"historical corpus hash mismatch for {path}")
        parts.append(data.decode("utf-8"))
    return "".join(parts)


def require_images() -> None:
    for container, expected in IMAGE_IDS.items():
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Image}}", container],
            check=True,
            capture_output=True,
            text=True,
        )
        actual = result.stdout.strip()
        if actual != expected:
            raise RuntimeError(
                f"container image mismatch for {container}: {actual} != {expected}"
            )


def load_stack_client():
    path = DATA / "stack_client.py"
    spec = importlib.util.spec_from_file_location("frozen_stack_client", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen STACK client")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def question_fragment(xml_all: str, rc_id: str) -> str:
    match = re.search(
        rf'<question type="stack">(?:(?!</question>).)*?'
        rf'<idnumber>{re.escape(rc_id)}</idnumber>.*?</question>',
        xml_all,
        re.S,
    )
    if not match:
        raise RuntimeError(f"STACK question not found in the source exports: {rc_id}")
    return match.group(0)


def recover(raw: str, policy: str) -> str | None:
    text = raw.strip()
    starts_with_marker = text.lower().startswith("answer")
    has_closing_tag = bool(re.search(r"</answer>\s*$", text, re.I))

    if policy == "strict":
        return None
    if policy == "closing_tag" and not (starts_with_marker and has_closing_tag):
        return None
    if policy == "bare_marker" and not starts_with_marker:
        return None
    if policy == "single_expression" and not starts_with_marker:
        nonempty = [line.strip() for line in text.splitlines() if line.strip()]
        return nonempty[0] if len(nonempty) == 1 else None
    if not starts_with_marker:
        return None

    candidate = text[len("answer"):].lstrip()
    if candidate.startswith(">"):
        candidate = candidate[1:].lstrip()
    candidate = re.sub(r"</answer>\s*$", "", candidate, flags=re.I).strip()
    if candidate.endswith("$"):
        candidate = candidate[:-1].rstrip()
    return candidate or None


def pairwise_disagreement(values: list[bool]) -> float:
    pairs = list(combinations(values, 2))
    return sum(left != right for left, right in pairs) / len(pairs)


def percentile_ci(values_by_question: dict[str, float]) -> list[float]:
    keys = sorted(values_by_question)
    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAPS):
        sample = [values_by_question[rng.choice(keys)] for _ in keys]
        draws.append(sum(sample) / len(sample))
    draws.sort()
    return [draws[int(0.025 * BOOTSTRAPS)], draws[int(0.975 * BOOTSTRAPS)]]


def summarize(rows: list[dict[str, str]]) -> dict:
    paper_scope = [row for row in rows if row["kind"] != "anchor"]
    fresh = [
        row for row in rows
        if row["kind"] == "fresh" and int(row["rep"]) == 0
    ]
    by_question: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in fresh:
        by_question[row["rc_id"]].append(row)
    if len(fresh) != 240 or len(by_question) != 60:
        raise RuntimeError("unexpected fresh-response frame")
    if any(len(group) != 4 for group in by_question.values()):
        raise RuntimeError("fresh-response groups must contain four instances")

    partition = Counter()
    mixed_gradable = invalid_only = format_only = 0
    for group in by_question.values():
        correct = sum(row["status"] == "correct" for row in group)
        partition[correct] += 1
        if not 0 < correct < 4:
            continue
        nonfull = [row["status"] for row in group if row["status"] != "correct"]
        if any(status in {"wrong", "partial"} for status in nonfull):
            mixed_gradable += 1
        else:
            invalid_only += 1
            if all(status in {"format_failure", "empty"} for status in nonfull):
                format_only += 1

    rep_groups: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in paper_scope:
        if row["kind"] in {"fresh", "replicate"}:
            rep_groups[(row["rc_id"], row["seed"])].append(
                row["status"] == "correct"
            )
    same: dict[str, list[float]] = defaultdict(list)
    for (rc_id, _seed), values in rep_groups.items():
        if len(values) == 3:
            same[rc_id].append(pairwise_disagreement(values))
    same_by_question = {
        rc_id: sum(values) / len(values)
        for rc_id, values in same.items()
        if len(values) == 2
    }
    cross_by_question = {
        rc_id: pairwise_disagreement(
            [row["status"] == "correct" for row in by_question[rc_id]]
        )
        for rc_id in same_by_question
    }
    delta_by_question = {
        rc_id: cross_by_question[rc_id] - same_by_question[rc_id]
        for rc_id in same_by_question
    }

    terminal = Counter(row["status"] for row in paper_scope)
    return {
        "paper_scope_rows": len(paper_scope),
        "paper_scope_terminal_statuses": dict(sorted(terminal.items())),
        "paper_scope_format_failures": terminal["format_failure"] + terminal["empty"],
        "fresh_full_credit": sum(
            row["status"] == "correct" for row in fresh
        ),
        "fresh_rows": len(fresh),
        "fresh_full_credit_rate": sum(
            row["status"] == "correct" for row in fresh
        ) / len(fresh),
        "fresh_partition_0_to_4": [partition[index] for index in range(5)],
        "fresh_mixed_questions": sum(partition[index] for index in (1, 2, 3)),
        "fresh_mixed_gradable": mixed_gradable,
        "fresh_invalid_only": invalid_only,
        "fresh_format_only": format_only,
        "replicate_questions": len(same_by_question),
        "same_prompt_disagreement": sum(same_by_question.values()) / len(same_by_question),
        "cross_instance_disagreement": sum(cross_by_question.values()) / len(cross_by_question),
        "cross_minus_same_prompt": sum(delta_by_question.values()) / len(delta_by_question),
        "cross_minus_same_prompt_ci": percentile_ci(delta_by_question),
    }


def main() -> None:
    require_hashes()
    require_images()
    xml_all = load_frozen_corpus()
    stack_client = load_stack_client()

    answers = [json.loads(line) for line in (DATA / "answers.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    result_rows = list(csv.DictReader((PRIMARY / "results.csv").open(encoding="utf-8")))
    model_results = [row for row in result_rows if row["model"] == MODEL]
    if len(model_results) != 322:
        raise RuntimeError("unexpected GLM-Z1 primary-result count")

    by_key = {
        (row["rc_id"], int(row["seed"]), int(row["rep"]), row["model"]): row
        for row in answers
    }
    instances = {
        (row["rc_id"], int(row["seed"])): row
        for row in (
            json.loads(line)
            for line in (DATA / "instances.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    failures = [row for row in model_results if row["status"] == "format_failure"]
    if len(failures) != 32:
        raise RuntimeError(f"expected 32 GLM-Z1 format failures, found {len(failures)}")

    fragments: dict[str, str] = {}
    regraded = {}
    detail_rows = []
    for row in failures:
        key = (row["rc_id"], int(row["seed"]), int(row["rep"]), MODEL)
        source = by_key[key]
        raw = source["raw_content"]
        candidate = recover(raw, "single_expression")
        if candidate is None:
            raise RuntimeError(f"single-expression recovery failed for {key}")
        instance = instances[(row["rc_id"], int(row["seed"]))]
        if row["rc_id"] not in fragments:
            fragments[row["rc_id"]] = question_fragment(xml_all, row["rc_id"])
        grade = stack_client.grade(
            fragments[row["rc_id"]],
            int(row["seed"]),
            {instance["input_name"]: candidate},
        )
        status = stack_client.classify_grade(grade, candidate)
        regraded[key] = {
            "candidate": candidate,
            "status": status,
            "score": grade.get("score"),
            "isgradable": bool(grade.get("isgradable")),
        }
        detail_rows.append({
            "rc_id": row["rc_id"],
            "seed": row["seed"],
            "rep": row["rep"],
            "kind": row["kind"],
            "raw_content_sha256": sha256_bytes(raw.encode("utf-8")),
            "closing_tag_eligible": int(recover(raw, "closing_tag") is not None),
            "bare_marker_eligible": int(recover(raw, "bare_marker") is not None),
            "single_expression_eligible": int(candidate is not None),
            "candidate": candidate,
            "candidate_sha256": sha256_bytes(candidate.encode("utf-8")),
            "regraded_status": status,
            "regraded_score": grade.get("score"),
            "regraded_isgradable": int(bool(grade.get("isgradable"))),
        })

    summaries = {}
    eligibility = {}
    for policy in ("strict", "closing_tag", "bare_marker", "single_expression"):
        updated = [dict(row) for row in model_results]
        eligible = 0
        for row in updated:
            key = (row["rc_id"], int(row["seed"]), int(row["rep"]), MODEL)
            if key not in regraded:
                continue
            raw = by_key[key]["raw_content"]
            if recover(raw, policy) is None:
                continue
            eligible += 1
            row["status"] = regraded[key]["status"]
            row["score"] = "" if regraded[key]["score"] is None else str(
                regraded[key]["score"]
            )
        eligibility[policy] = eligible
        summaries[policy] = summarize(updated)

    primary_analysis = json.loads((PRIMARY / "analysis.json").read_text(
        encoding="utf-8"
    ))["models"][MODEL]

    summary = {
        "audit_status": "post_hoc_sensitivity",
        "model": MODEL,
        "primary_policy": "strict <answer>...</answer> extraction",
        "format_failure_rows": len(failures),
        "format_failure_rows_by_kind": dict(sorted(Counter(
            row["kind"] for row in failures
        ).items())),
        "eligible_rows_by_policy": eligibility,
        "regraded_statuses_all_32": dict(sorted(Counter(
            value["status"] for value in regraded.values()
        ).items())),
        "primary_analysis": {
            "fresh_full_credit_rate": primary_analysis["fresh_acc"],
            "fresh_full_credit_ci": primary_analysis["fresh_ci"],
            "fresh_all_some_none": primary_analysis["consistency_all_some_none"],
            "same_prompt_disagreement":
                primary_analysis["same_prompt_disagreement"],
            "cross_instance_disagreement":
                primary_analysis["cross_seed_disagreement"],
            "cross_minus_same_prompt":
                primary_analysis["cross_minus_same_prompt"],
            "cross_minus_same_prompt_ci":
                primary_analysis["cross_minus_same_prompt_ci"],
        },
        "policies": summaries,
        "bootstrap": {
            "unit": "question",
            "samples": BOOTSTRAPS,
            "seed": BOOTSTRAP_SEED,
        },
        "engine_image_ids": IMAGE_IDS,
    }

    detail_rows.sort(key=lambda row: (
        row["kind"], row["rc_id"], int(row["seed"]), int(row["rep"])
    ))
    with (HERE / "per_response.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detail_rows[0]))
        writer.writeheader()
        writer.writerows(detail_rows)
    (HERE / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
