#!/usr/bin/env python3
"""Freeze the response scope used by the randomized-instance manuscript analysis.

The original experiment artifact contains three response roles: four primary
instances per question (``fresh``), extra calls for the same-prompt comparison
(``replicate``), and a source-seed comparison using seeds retained in course exports
(``anchor``).  The manuscript analyzes the first two roles.  This script does
not alter the frozen experiment; it records the exclusion rule, binds it to the
source hashes, and recomputes every affected aggregate.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
RAW_RESULTS = ROOT / "variant_study/results.csv"
RAW_MANIFEST = ROOT / "variant_study/grade_manifest.json"
RAW_ANALYSIS = ROOT / "variant_study/analysis.json"
# The outer-brace results with the raw verdict of every row next to the
# final one (not included; sensitivity/outer_brace_regrade/ holds the run).
BRACE_RESULTS = ROOT / "not_included/outer_brace_regrade_results.csv"
QUESTION_FEATURES = ROOT / "grading_contract_audit/question_features.csv"
OUT_DIR = ROOT / "variant_study/recomputed"
OUT_JSON = OUT_DIR / "paper_scope_summary.json"

PAPER_KINDS = {"fresh", "replicate"}
ARCHIVED_KINDS = {"anchor"}
DECISIVE_STATUSES = {"correct", "wrong", "partial"}
CHECKERS = ("string_eq", "sympy_eq", "math_verify_eq")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row["model"],
        row["rc_id"],
        row["kind"],
        row["seed"],
        row["rep"],
    )


def key_digest(rows: Iterable[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for key in sorted(response_key(row) for row in rows):
        digest.update("\0".join(key).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def percentage(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def checker_summary(
    rows: list[dict[str, str]],
    contract_class: dict[str, str],
) -> dict[str, object]:
    decisive = [row for row in rows if row["status"] in DECISIVE_STATUSES]
    output: dict[str, object] = {
        "decisive_stack_outcomes": len(decisive),
        "methods": {},
    }
    for checker in CHECKERS:
        covered = [row for row in decisive if row[checker] in {"0", "1"}]
        agreements = [
            row
            for row in covered
            if ((row["status"] == "correct") == (row[checker] == "1"))
        ]
        disagreements = [row for row in covered if row not in agreements]
        method = {
            "coverage_n": len(covered),
            "coverage_percent": percentage(len(covered), len(decisive)),
            "no_verdict_n": len(decisive) - len(covered),
            "agreement_n": len(agreements),
            "conditional_agreement_percent": percentage(
                len(agreements), len(covered)
            ),
            "false_reject_n": sum(
                row["status"] == "correct" and row[checker] == "0"
                for row in disagreements
            ),
            "false_accept_n": sum(
                row["status"] != "correct" and row[checker] == "1"
                for row in disagreements
            ),
            "disagreement_question_n": len(
                {row["rc_id"] for row in disagreements}
            ),
            "by_contract": {},
        }
        for label in ("direct_equivalence_only", "richer_prt_logic"):
            subset = [row for row in decisive if contract_class[row["rc_id"]] == label]
            subset_covered = [row for row in subset if row[checker] in {"0", "1"}]
            subset_agreements = [
                row
                for row in subset_covered
                if ((row["status"] == "correct") == (row[checker] == "1"))
            ]
            subset_disagreements = [
                row for row in subset_covered if row not in subset_agreements
            ]
            method["by_contract"][label] = {  # type: ignore[index]
                "decisive_n": len(subset),
                "coverage_n": len(subset_covered),
                "coverage_percent": percentage(len(subset_covered), len(subset)),
                "agreement_n": len(subset_agreements),
                "conditional_agreement_percent": percentage(
                    len(subset_agreements), len(subset_covered)
                ),
                "disagreement_n": len(subset_disagreements),
                "disagreement_question_n": len(
                    {row["rc_id"] for row in subset_disagreements}
                ),
            }
        output["methods"][checker] = method  # type: ignore[index]
    return output


def load_contract_classes(required_ids: set[str]) -> dict[str, str]:
    classes = {}
    with QUESTION_FEATURES.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            direct = row["direct_equivalence_only"] == "True"
            richer = row["prt_logic_beyond_direct_equivalence"] == "True"
            if row["rc_id"] not in required_ids:
                continue
            if direct == richer:
                raise SystemExit(
                    f"question has ambiguous grading-contract class: {row['rc_id']}"
                )
            classes[row["rc_id"]] = (
                "direct_equivalence_only" if direct else "richer_prt_logic"
            )
    return classes


def status_summary(rows: list[dict[str, str]]) -> dict[str, int]:
    return dict(sorted(Counter(row["status"] for row in rows).items()))


def per_model_summary(rows: list[dict[str, str]]) -> dict[str, object]:
    output = {}
    for model in sorted({row["model"] for row in rows}):
        model_rows = [row for row in rows if row["model"] == model]
        primary = [
            row
            for row in model_rows
            if row["kind"] == "fresh" and row["rep"] == "0"
        ]
        repeated = [row for row in model_rows if row["kind"] == "replicate"]
        output[model] = {
            "responses": len(model_rows),
            "primary_instance_responses": len(primary),
            "same_prompt_additional_responses": len(repeated),
            "status_counts": status_summary(model_rows),
            "format_failures": sum(
                row["status"] == "format_failure" for row in model_rows
            ),
            "primary_full_credit_n": sum(
                row["status"] == "correct" for row in primary
            ),
            "primary_full_credit_percent": percentage(
                sum(row["status"] == "correct" for row in primary), len(primary)
            ),
        }
    return output


def brace_sensitivity(
    raw_rows: list[dict[str, str]],
    paper_rows: list[dict[str, str]],
) -> dict[str, object]:
    with BRACE_RESULTS.open(encoding="utf-8", newline="") as handle:
        sensitivity_rows = list(csv.DictReader(handle))
    raw_by_key = {response_key(row): row for row in raw_rows}
    sensitivity_by_key = {response_key(row): row for row in sensitivity_rows}
    if len(raw_by_key) != len(raw_rows) or len(sensitivity_by_key) != len(sensitivity_rows):
        raise SystemExit("duplicate response key in primary or brace-sensitivity grid")
    if set(raw_by_key) != set(sensitivity_by_key):
        raise SystemExit("brace-sensitivity grid differs from the primary response grid")

    changed_keys = []
    for key, row in sensitivity_by_key.items():
        raw = raw_by_key[key]
        if (
            row["answer"] != raw["answer"]
            or row["raw_status"] != raw["status"]
            or row["raw_score"] != raw["score"]
        ):
            raise SystemExit(f"brace-sensitivity raw provenance differs for {key}")
        if row["status"] != raw["status"] or row["score"] != raw["score"]:
            changed_keys.append(key)

    paper_keys = {response_key(row) for row in paper_rows}
    return {
        "changed_responses_all_roles": len(changed_keys),
        "changed_responses_paper_scope": sum(key in paper_keys for key in changed_keys),
        "changed_responses_archived_role": sum(
            key not in paper_keys for key in changed_keys
        ),
    }


def main() -> None:
    with RAW_RESULTS.open(encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    manifest = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("rows") != len(raw_rows):
        raise SystemExit("raw row count differs from the frozen grade manifest")
    if manifest.get("sha256", {}).get("results") != sha256(RAW_RESULTS):
        raise SystemExit("raw results hash differs from the frozen grade manifest")

    observed_kinds = {row["kind"] for row in raw_rows}
    if observed_kinds != PAPER_KINDS | ARCHIVED_KINDS:
        raise SystemExit(f"unexpected response roles: {sorted(observed_kinds)}")
    paper_rows = [row for row in raw_rows if row["kind"] in PAPER_KINDS]
    archived_rows = [row for row in raw_rows if row["kind"] in ARCHIVED_KINDS]
    if len(paper_rows) + len(archived_rows) != len(raw_rows):
        raise SystemExit("paper and archived scopes do not partition the raw grid")

    models = sorted({row["model"] for row in raw_rows})
    if len(models) != 5:
        raise SystemExit(f"expected five model profiles, found {len(models)}")
    model_summary = per_model_summary(paper_rows)
    for model, stats in model_summary.items():
        if (
            stats["responses"] != 288
            or stats["primary_instance_responses"] != 240
            or stats["same_prompt_additional_responses"] != 48
        ):
            raise SystemExit(f"unexpected paper-scope grid for {model}: {stats}")
    if len(archived_rows) != 170:
        raise SystemExit(f"expected 170 archived responses, found {len(archived_rows)}")

    response_ids = {row["rc_id"] for row in raw_rows}
    contract_class = load_contract_classes(response_ids)
    missing_features = sorted(response_ids - set(contract_class))
    if missing_features:
        raise SystemExit(f"response questions missing contract features: {missing_features}")

    summary = {
        "schema": "manuscript_response_scope_v1",
        "scope_decision": {
            "paper_response_roles": sorted(PAPER_KINDS),
            "archived_response_roles": sorted(ARCHIVED_KINDS),
            "rationale": (
                "The manuscript evaluates independently generated instances and "
                "the prespecified same-prompt replicate comparison. Responses at "
                "seeds retained in source-course exports remain in the frozen "
                "artifact but are excluded from manuscript aggregates because the "
                "source-course seed-selection process is undocumented."
            ),
            "model_calls_added_or_removed": 0,
            "frozen_source_rows_modified": 0,
        },
        "inputs": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                RAW_RESULTS,
                RAW_MANIFEST,
                RAW_ANALYSIS,
            )
        },
        "frozen_grid": {
            "responses": len(raw_rows),
            "models": len(models),
            "response_roles": dict(sorted(Counter(row["kind"] for row in raw_rows).items())),
            "response_key_sha256": key_digest(raw_rows),
        },
        "archived_source_seed_comparison": {
            "responses": len(archived_rows),
            "questions": len({row["rc_id"] for row in archived_rows}),
            "models": len({row["model"] for row in archived_rows}),
            "response_key_sha256": key_digest(archived_rows),
            "question_ids": sorted({row["rc_id"] for row in archived_rows}),
            "prespecified_analysis_preserved_at": str(RAW_ANALYSIS.relative_to(ROOT)),
        },
        "paper_scope": {
            "responses": len(paper_rows),
            "questions": len({row["rc_id"] for row in paper_rows}),
            "models": len(models),
            "responses_per_model": 288,
            "primary_instance_responses_per_model": 240,
            "same_prompt_additional_responses_per_model": 48,
            "response_key_sha256": key_digest(paper_rows),
            "status_counts": status_summary(paper_rows),
            "models_detail": model_summary,
            "checker_diagnostics": checker_summary(paper_rows, contract_class),
            "brace_sensitivity": brace_sensitivity(raw_rows, paper_rows),
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {OUT_JSON.relative_to(ROOT)}: "
        f"{len(paper_rows)} paper-scope + {len(archived_rows)} archived responses"
    )


if __name__ == "__main__":
    main()
