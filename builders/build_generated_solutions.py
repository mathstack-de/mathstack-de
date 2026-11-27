#!/usr/bin/env python3
"""Build the linked release table for model-generated worked solutions.

The canonical source table retains only the 111
solutions approved by the mathematics expert. This auxiliary research table
also exposes the 141 stronger machine-checked candidates that were used as
concept-labeling context but did not receive question-level expert review.

The two release tiers must remain distinguishable. Full STACK credit applies
to the structured final answer submitted during generation; it does not prove
that every explanatory step in the worked solution is correct.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"

SOURCE = OUT / "data/source/all-00000-of-00001.parquet"
FULL_REGISTER = (
    ROOT
    / "not_included/worked_solution_generation"
    / "ai_generalfeedback_register.csv"
)
MACHINE_OVERLAY = (
    ROOT
    / "not_included/worked_solution_generation"
    / "annotation_context_overlay.jsonl"
)
EXPERT_REGISTER = ROOT / "not_included/ai_generalfeedback_release_register.csv"
EXPERT_MANIFEST = (
    ROOT
    / "not_included/worked_solution_generation/expert_review_xml"
    / "expert_approved_release/manifest.json"
)

OUTPUT = OUT / "data/generated_worked_solutions/all-00000-of-00001.parquet"
MANIFEST = OUT / "manifests/generated_worked_solutions_manifest.json"

SCHEMA_VERSION = "generated_solutions_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_int(value: object) -> int:
    return int(str(value).strip() or "0")


def main() -> None:
    required = [
        SOURCE,
        FULL_REGISTER,
        MACHINE_OVERLAY,
        EXPERT_REGISTER,
        EXPERT_MANIFEST,
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing generated-solution inputs: {missing}")

    source = pq.read_table(SOURCE).to_pandas().set_index("rc_id", drop=False)
    full_rows = read_csv(FULL_REGISTER)
    full_by_id = {row["rc_id"]: row for row in full_rows}
    expert_rows = read_csv(EXPERT_REGISTER)
    expert_by_id = {row["rc_id"]: row for row in expert_rows}
    machine_rows = [
        json.loads(line)
        for line in MACHINE_OVERLAY.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    machine_by_id = {row["rc_id"]: row for row in machine_rows}
    expert_manifest = json.loads(EXPERT_MANIFEST.read_text(encoding="utf-8"))

    if len(full_by_id) != 255 or len(full_rows) != 255:
        raise SystemExit("full-credit generation register must contain 255 unique rows")
    if len(expert_by_id) != 111 or len(expert_rows) != 111:
        raise SystemExit("expert-approved register must contain 111 unique rows")
    if len(machine_by_id) != 141 or len(machine_rows) != 141:
        raise SystemExit("machine-checked overlay must contain 141 unique rows")
    if set(expert_by_id) & set(machine_by_id):
        raise SystemExit("expert-approved and machine-checked tiers must be disjoint")

    excluded = set(full_by_id) - set(expert_by_id) - set(machine_by_id)
    expected_excluded = set(expert_manifest.get("excluded_rc_ids", []))
    if excluded != expected_excluded or len(excluded) != 3:
        raise SystemExit(
            "expanded release must exclude exactly the one rejected and two "
            f"unconfirmed rows; found {sorted(excluded)}"
        )

    release_rows: list[dict[str, object]] = []

    for rc_id in sorted(expert_by_id):
        if rc_id not in source.index or rc_id not in full_by_id:
            raise SystemExit(f"expert-approved row missing source lineage: {rc_id}")
        source_row = source.loc[rc_id]
        final_register = expert_by_id[rc_id]
        generation = full_by_id[rc_id]
        html = source_row.generalfeedback_html
        if not isinstance(html, str) or not html.strip():
            raise SystemExit(f"expert-approved solution absent from source: {rc_id}")
        if source_row.gf_author_code != "AI":
            raise SystemExit(f"expert-approved solution lacks AI authorship: {rc_id}")
        if not str(source_row.gf_provenance).startswith("ai_generated"):
            raise SystemExit(f"expert-approved solution lacks AI provenance: {rc_id}")
        if final_register["release_status"] != "included_release_ready":
            raise SystemExit(f"expert-approved row is not release-ready: {rc_id}")
        if not parse_bool(generation["stack_full_credit"]):
            raise SystemExit(f"expert-approved row lacks generation full credit: {rc_id}")

        release_rows.append(
            {
                "dataset_version": source_row.dataset_version,
                "schema_version": SCHEMA_VERSION,
                "rc_id": rc_id,
                "worked_solution_html": html,
                "gf_author_code": "AI",
                "content_license": "CC-BY-SA-4.0",
                "release_tier": "expert_approved",
                "expert_review_status": "approved",
                "annotation_context_used": True,
                "generation_provider": generation["generation_provider"],
                "generation_model": generation["generation_model"],
                "generation_mode": generation["generation_mode"],
                "teacher_answer_exposed_during_generation": parse_bool(
                    generation["tans_exposed"]
                ),
                "generation_candidate_stack_score": float(generation["stack_score"]),
                "generation_candidate_full_credit": True,
                "generation_candidate_presentation_clean": parse_bool(
                    generation["presentation_ok"]
                ),
                "generation_candidate_result_match": parse_bool(
                    generation["gf_answer_ok"]
                ),
                "generation_verification_status": generation[
                    "gf_verification_status"
                ],
                "generation_links_checked": parse_int(generation["links_checked"]),
                "generation_links_supported": parse_int(
                    generation["links_verified"]
                ),
                "generation_links_flagged": parse_int(generation["links_refuted"]),
                "generated_candidate_sha256": generation["candidate_sha256"],
                "released_solution_sha256": sha256_text(html),
                "generation_record_sha256": generation[
                    "generation_record_sha256"
                ],
                "question_sha256": generation["question_sha256"],
            }
        )

    for rc_id in sorted(machine_by_id):
        if rc_id not in source.index or rc_id not in full_by_id:
            raise SystemExit(f"machine-checked row missing source lineage: {rc_id}")
        source_row = source.loc[rc_id]
        overlay = machine_by_id[rc_id]
        generation = full_by_id[rc_id]
        html = overlay["generalfeedback_html"]
        if bool(source_row.has_generalfeedback):
            raise SystemExit(
                f"machine-only solution unexpectedly present in approved source: {rc_id}"
            )
        if sha256_text(html) != overlay["generalfeedback_sha256"]:
            raise SystemExit(f"machine-checked overlay hash mismatch: {rc_id}")
        if overlay["generalfeedback_sha256"] != generation["candidate_sha256"]:
            raise SystemExit(f"machine/full-register candidate mismatch: {rc_id}")
        if not (
            parse_bool(generation["stack_full_credit"])
            and parse_bool(generation["presentation_ok"])
            and parse_bool(generation["gf_answer_ok"])
            and parse_int(generation["links_refuted"]) == 0
            and parse_bool(generation["conservative_context_eligible"])
        ):
            raise SystemExit(f"machine release criteria not met: {rc_id}")

        release_rows.append(
            {
                "dataset_version": source_row.dataset_version,
                "schema_version": SCHEMA_VERSION,
                "rc_id": rc_id,
                "worked_solution_html": html,
                "gf_author_code": "AI",
                "content_license": "CC-BY-SA-4.0",
                "release_tier": "machine_checked_not_expert_reviewed",
                "expert_review_status": "not_reviewed",
                "annotation_context_used": True,
                "generation_provider": generation["generation_provider"],
                "generation_model": generation["generation_model"],
                "generation_mode": generation["generation_mode"],
                "teacher_answer_exposed_during_generation": parse_bool(
                    generation["tans_exposed"]
                ),
                "generation_candidate_stack_score": float(generation["stack_score"]),
                "generation_candidate_full_credit": True,
                "generation_candidate_presentation_clean": True,
                "generation_candidate_result_match": True,
                "generation_verification_status": generation[
                    "gf_verification_status"
                ],
                "generation_links_checked": parse_int(generation["links_checked"]),
                "generation_links_supported": parse_int(
                    generation["links_verified"]
                ),
                "generation_links_flagged": 0,
                "generated_candidate_sha256": generation["candidate_sha256"],
                "released_solution_sha256": sha256_text(html),
                "generation_record_sha256": generation[
                    "generation_record_sha256"
                ],
                "question_sha256": generation["question_sha256"],
            }
        )

    frame = pd.DataFrame(release_rows).sort_values("rc_id").reset_index(drop=True)
    if len(frame) != 252 or not frame.rc_id.is_unique:
        raise SystemExit("expanded generated-solution table must contain 252 unique rows")

    schema = pa.schema(
        [
            ("dataset_version", pa.string()),
            ("schema_version", pa.string()),
            ("rc_id", pa.string()),
            ("worked_solution_html", pa.string()),
            ("gf_author_code", pa.string()),
            ("content_license", pa.string()),
            ("release_tier", pa.string()),
            ("expert_review_status", pa.string()),
            ("annotation_context_used", pa.bool_()),
            ("generation_provider", pa.string()),
            ("generation_model", pa.string()),
            ("generation_mode", pa.string()),
            ("teacher_answer_exposed_during_generation", pa.bool_()),
            ("generation_candidate_stack_score", pa.float64()),
            ("generation_candidate_full_credit", pa.bool_()),
            ("generation_candidate_presentation_clean", pa.bool_()),
            ("generation_candidate_result_match", pa.bool_()),
            ("generation_verification_status", pa.string()),
            ("generation_links_checked", pa.int64()),
            ("generation_links_supported", pa.int64()),
            ("generation_links_flagged", pa.int64()),
            ("generated_candidate_sha256", pa.string()),
            ("released_solution_sha256", pa.string()),
            ("generation_record_sha256", pa.string()),
            ("question_sha256", pa.string()),
        ]
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(frame, schema=schema, preserve_index=False), OUTPUT
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "rows": len(frame),
        "release_tier_counts": frame.release_tier.value_counts().to_dict(),
        "annotation_context_rows_released": int(frame.annotation_context_used.sum()),
        "annotation_context_full_credit_total": 255,
        "excluded_full_credit_rows": sorted(excluded),
        "excluded_full_credit_disposition": {
            "expert_rejected": 1,
            "expert_unconfirmed": 2,
        },
        "claim_boundary": (
            "generation_candidate_full_credit refers only to the structured final "
            "answer submitted to STACK. It does not verify every explanatory step."
        ),
        "input_sha256": {
            str(path.relative_to(ROOT)): sha256(path) for path in required
        },
        "output_sha256": sha256(OUTPUT),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "wrote generated worked solutions: 252 rows "
        "(111 expert-approved, 141 machine-checked/not expert-reviewed)"
    )


if __name__ == "__main__":
    main()
