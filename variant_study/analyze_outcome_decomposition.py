#!/usr/bin/env python3
"""Decompose mixed outcomes in the frozen four-instance response study.

The primary analysis counts every invalid model output as incorrect. This
post-hoc descriptive analysis retains that result and separates mixed questions
that contain both full- and non-full-credit STACK-gradable responses from mixed
questions caused only by invalid output.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "variant_study/results.csv"
OUT_DIR = ROOT / "variant_study/recomputed"
OUT_JSON = OUT_DIR / "outcome_decomposition.json"

GRADABLE_NON_FULL_CREDIT = {"wrong", "partial"}
INVALID = {"format_failure", "syntax_invalid", "empty"}
EXPECTED_STATUSES = {"correct", *GRADABLE_NON_FULL_CREDIT, *INVALID}

MODEL_LABELS = {
    "gpt-5-2025-08-07": "GPT-5",
    "qwen3:32b": "Qwen3-32B",
    "gemma4:31b": "Gemma 4-31B",
    "hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M": "GLM-Z1-32B",
    "hf.co/unsloth/GLM-4-32B-0414-GGUF:Q4_K_M": "GLM-4-32B",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_template(statuses: list[str]) -> str:
    """Classify one question from its four prespecified fresh responses."""
    if len(statuses) != 4:
        raise ValueError(f"expected four outcomes, got {len(statuses)}")
    unknown = set(statuses) - EXPECTED_STATUSES
    if unknown:
        raise ValueError(f"unknown outcome statuses: {sorted(unknown)}")

    correct = statuses.count("correct")
    if correct == 4:
        return "all_four_full_credit"
    if correct == 0:
        return "no_full_credit"
    if any(status in GRADABLE_NON_FULL_CREDIT for status in statuses):
        return "mixed_gradable"
    if all(status == "correct" or status in INVALID for status in statuses):
        return "mixed_invalid_only"
    raise AssertionError(f"unclassified outcome pattern: {statuses}")


def analyze(results_path: Path = RESULTS) -> dict[str, object]:
    rows = list(csv.DictReader(results_path.open(encoding="utf-8")))
    fresh = [
        row for row in rows
        if row["kind"] == "fresh" and row["rep"] == "0"
    ]
    models = sorted({row["model"] for row in fresh})
    if set(models) != set(MODEL_LABELS):
        raise SystemExit(f"unexpected model set: {models}")

    output_models = {}
    for model in models:
        model_rows = [row for row in fresh if row["model"] == model]
        by_question: dict[str, list[str]] = defaultdict(list)
        seen_keys = set()
        for row in model_rows:
            key = (row["rc_id"], row["seed"])
            if key in seen_keys:
                raise SystemExit(f"duplicate fresh response: {model} {key}")
            seen_keys.add(key)
            by_question[row["rc_id"]].append(row["status"])

        if len(model_rows) != 240 or len(by_question) != 60:
            raise SystemExit(
                f"incomplete fresh grid for {model}: "
                f"{len(model_rows)} rows, {len(by_question)} questions"
            )

        categories = Counter()
        status_counts = Counter()
        strict_correct_counts = Counter()
        mixed_contains_format = 0
        mixed_format_only = 0
        mixed_syntax_only = 0
        agreeing_pairs = 0
        total_pairs = 0

        for rc_id, statuses in by_question.items():
            if len(statuses) != 4:
                raise SystemExit(f"{model} {rc_id}: expected four fresh outcomes")
            category = classify_template(statuses)
            categories[category] += 1
            status_counts.update(statuses)
            correct = statuses.count("correct")
            strict_correct_counts[correct] += 1

            if category.startswith("mixed_"):
                mixed_contains_format += "format_failure" in statuses
                mixed_format_only += set(statuses) <= {"correct", "format_failure"}
                mixed_syntax_only += set(statuses) <= {"correct", "syntax_invalid"}

            agreeing_pairs += correct * (correct - 1) // 2
            non_correct = 4 - correct
            agreeing_pairs += non_correct * (non_correct - 1) // 2
            total_pairs += 6

        expected_categories = {
            "all_four_full_credit",
            "mixed_gradable",
            "mixed_invalid_only",
            "no_full_credit",
        }
        if set(categories) - expected_categories or sum(categories.values()) != 60:
            raise SystemExit(f"invalid category partition for {model}: {categories}")

        gradable_n = sum(
            count for status, count in status_counts.items()
            if status == "correct" or status in GRADABLE_NON_FULL_CREDIT
        )
        output_models[model] = {
            "label": MODEL_LABELS[model],
            "questions": 60,
            "fresh_responses": 240,
            "categories": {
                name: categories[name]
                for name in (
                    "all_four_full_credit",
                    "mixed_gradable",
                    "mixed_invalid_only",
                    "no_full_credit",
                )
            },
            "strict_correct_count_distribution_0_to_4": [
                strict_correct_counts[count] for count in range(5)
            ],
            "status_counts": dict(sorted(status_counts.items())),
            "mixed_contains_format_failure": mixed_contains_format,
            "mixed_format_failure_only": mixed_format_only,
            "mixed_syntax_invalid_only": mixed_syntax_only,
            "strict_pairwise_outcome_agreement": round(
                agreeing_pairs / total_pairs, 6
            ),
            "gradable_responses": gradable_n,
            "full_credit_given_gradable": round(
                status_counts["correct"] / gradable_n, 6
            ) if gradable_n else None,
        }

    return {
        "schema": "outcome_decomposition_v1",
        "analysis_role": "post_hoc_descriptive_sensitivity",
        "primary_rule": "invalid outputs count as incorrect",
        "definitions": {
            "mixed_gradable": (
                "at least one full-credit and one non-full-credit "
                "STACK-gradable response"
            ),
            "mixed_invalid_only": (
                "at least one full-credit response; every non-full-credit "
                "outcome is invalid rather than STACK-gradable"
            ),
        },
        "inputs": {
            str(results_path.relative_to(ROOT)): sha256(results_path),
        },
        "models": output_models,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = analyze()
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
