#!/usr/bin/env python3
"""Build the expert-label-free bundle used by the GBERT training server."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "data" / "concept_tagging.csv"
LABEL_SPACE = HERE / "data" / "label_space.json"
SPLIT_MANIFEST = HERE / "splits" / "split_manifest.json"
OUT = HERE / "server_bundle"
EXPECTED_COUNTS = {
    "train": 1802,
    "dev": 318,
    "test_probability": 140,
    "test_diagnostic": 60,
}
SERVER_COLUMNS = ["question_id", "split", "input_text", "labels_model_generated"]
TEST_SPLITS = {"test_probability", "test_diagnostic"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(out: Path = OUT) -> dict:
    for path in (SOURCE, LABEL_SPACE, SPLIT_MANIFEST):
        if not path.is_file():
            raise SystemExit(f"missing GBERT input: {path}")

    split_manifest = json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))
    expected_source_hash = split_manifest["outputs_sha256"]["table"]
    if sha256(SOURCE) != expected_source_hash:
        raise SystemExit("modeling table differs from the frozen split manifest")

    frame = pd.read_csv(SOURCE, keep_default_na=False)
    missing = set(SERVER_COLUMNS) - set(frame.columns)
    if missing:
        raise SystemExit(f"modeling table lacks server columns: {sorted(missing)}")
    counts = frame["split"].value_counts().to_dict()
    if counts != split_manifest["counts"]:
        raise SystemExit(
            f"modeling-table split counts differ from manifest: {counts}"
        )

    bundle = frame[
        frame["split"].isin(EXPECTED_COUNTS)
    ][SERVER_COLUMNS].copy()
    bundle_counts = bundle["split"].value_counts().to_dict()
    if bundle_counts != EXPECTED_COUNTS:
        raise SystemExit(f"unexpected server-bundle counts: {bundle_counts}")

    # The server needs test inputs for inference, never test supervision.
    bundle.loc[bundle["split"].isin(TEST_SPLITS), "labels_model_generated"] = ""
    if bundle.loc[
        bundle["split"].isin(TEST_SPLITS), "labels_model_generated"
    ].ne("").any():
        raise SystemExit("test labels remain in the server bundle")

    out.mkdir(parents=True, exist_ok=True)
    bundle_path = out / "concept_tagging.csv"
    label_path = out / "label_space.json"
    bundle.to_csv(bundle_path, index=False, lineterminator="\n")
    label_path.write_bytes(LABEL_SPACE.read_bytes())

    manifest = {
        "record_type": "gbert_server_bundle",
        "rows": len(bundle),
        "counts": EXPECTED_COUNTS,
        "columns": SERVER_COLUMNS,
        "expert_columns_present": False,
        "test_labels_present": False,
        "sha256": {
            "source_modeling_table": sha256(SOURCE),
            "source_split_manifest": sha256(SPLIT_MANIFEST),
            "source_label_space": sha256(LABEL_SPACE),
            "server_modeling_table": sha256(bundle_path),
            "server_label_space": sha256(label_path),
            "builder": sha256(Path(__file__)),
        },
    }
    manifest_path = out / "bundle_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "GBERT server bundle ready: "
        f"{len(bundle)} rows, no expert columns or test labels"
    )
    return manifest


def main() -> None:
    build_bundle()


if __name__ == "__main__":
    main()
