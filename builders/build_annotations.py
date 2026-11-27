#!/usr/bin/env python3
"""Build the annotations table from the normalized model-generated label output.

The normalization stage folds and deduplicates labels, recovers structured
outputs, checks duplicate questions, and fails on invalid records. This builder
converts that validated CSV to the release Arrow schema.

The expert reference and model-generated labels remain separate; each row
records its annotation layer and producer.

Inputs:
  not_included/model_generated_labels_v1_1/
      model_generated_labels_v1_1.csv
      model_generated_labels_v1_1.manifest.json
      (output of the normalization stage and producer identity)
  out/data/source/*.parquet                          (question types for variant ids)

Refuses to build unless the manifest exists and the CSV carries only
accepted statuses. concept_ids and concept_labels_de stay pair-aligned in the
canonical emission order.

Usage: python build_annotations.py [normalized_csv manifest_json]
       (default: the normalization output above)
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = HERE / "out"


def default_inputs():
    directory = ROOT / "not_included/model_generated_labels_v1_1"
    return (directory / "model_generated_labels_v1_1.csv",
            directory / "model_generated_labels_v1_1.manifest.json")


if len(sys.argv) == 1:
    SRC, MAN = default_inputs()
elif len(sys.argv) == 3:
    SRC, MAN = Path(sys.argv[1]), Path(sys.argv[2])
else:
    sys.exit("usage: build_annotations.py [normalized_csv manifest_json]")
POLICY_VERSION = "ANNOTATION_POLICY_v1.1"
VOCAB_VERSION = "v1.1_2026-07"
PASSING = {"tagged", "tagged_recovered", "valid_empty", "valid_empty_recovered"}


def portable_producer_paths(value):
    """Make nested producer path fields portable without changing run metadata."""
    if isinstance(value, dict):
        portable = {}
        for key, child in value.items():
            if key == "path" and isinstance(child, str):
                path = Path(child)
                if path.is_absolute():
                    try:
                        child = str(path.relative_to(ROOT))
                    except ValueError:
                        child = path.name
            portable[key] = portable_producer_paths(child)
        return portable
    if isinstance(value, list):
        return [portable_producer_paths(item) for item in value]
    return value


def main():
    if not (SRC.exists() and MAN.exists()):
        sys.exit("canonical normalized model_generated output missing — run "
                 "the normalization step first")
    manifest = json.loads(MAN.read_text(encoding="utf-8"))
    run_manifest_sha = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    model = manifest.get("model") or "unknown"

    # authenticate the canonical CSV against the manifest's recorded hash
    csv_sha = hashlib.sha256(SRC.read_bytes()).hexdigest()
    recorded = (manifest.get("sha256") or {}).get("output")
    if recorded != csv_sha:
        sys.exit(f"normalized CSV does not match manifest output hash "
                 f"({csv_sha[:12]} != {str(recorded)[:12]}) — stale or tampered input")

    norm = pd.read_csv(SRC, encoding="utf-8-sig", keep_default_na=False)
    if norm.rc_id.nunique() != 2403 or len(norm) != 2403:
        sys.exit(f"expected 2,403 unique rc_ids, got {norm.rc_id.nunique()}/{len(norm)}")
    bad = set(norm.status) - PASSING
    if bad:
        sys.exit(f"non-passing statuses in canonical output: {bad} — "
                 "the full-coverage check must pass before building")

    # question types -> honest input_variant_id (only STACK text is
    # maxima-instantiated; other types pass through the same pipeline unevaluated)
    src = pq.read_table(
        OUT / "data/source/all-00000-of-00001.parquet",
        columns=["rc_id", "question_type", "topic_path"],
    ).to_pandas()
    qtype = dict(zip(src.rc_id, src.question_type))
    topic_path = dict(zip(src.rc_id, src.topic_path))
    unknown = set(norm.rc_id) - set(src.rc_id)
    if unknown:
        sys.exit(f"{len(unknown)} annotation rc_ids not in the source table")
    label2id = json.loads((OUT / "vocabulary/label2id.json").read_text(encoding="utf-8"))

    rows = []
    for _, r in norm.iterrows():
        ids = [x for x in r["concept_ids"].split("|") if x]
        labels = [x for x in r["concept_labels"].split("|") if x]
        if len(ids) != len(labels):
            sys.exit(f"id/label length mismatch in {r['rc_id']}")
        if ids != [label2id.get(lb) for lb in labels]:
            sys.exit(f"id/label pair mismatch in {r['rc_id']}")
        if ids != sorted(ids):
            sys.exit(f"non-canonical concept order in {r['rc_id']}")
        qt = qtype.get(r["rc_id"], "unknown")
        rows.append({
            "annotation_id": f"model_generated-{model}-{r['rc_id']}",
            "rc_id": r["rc_id"],
            "annotation_layer": "model_generated",
            "annotator_id": f"anthropic:{model}",
            "reference_role": "not_applicable",
            "concept_ids": ids,                # pair-aligned with labels
            "concept_labels_de": labels,
            "annotation_status": r["status"],
            "recovered": int(r.get("recovered", 0) or 0),
            "unmapped_model_suggestions": r.get("oov_terms", "") or None,
            "policy_version": POLICY_VERSION,
            "vocabulary_version": VOCAB_VERSION,
            "input_variant_id": ("maxima_evaluated_seed42" if qt == "stack"
                                 else "source_text_unevaluated"),
            "input_fields_used": "questiontext+answeroptions+generalfeedback",
            "run_manifest_sha256": run_manifest_sha,
            "adjudication_status": "not_applicable",
        })

    df = pd.DataFrame(rows)
    schema = pa.schema([
        ("annotation_id", pa.string()), ("rc_id", pa.string()),
        ("annotation_layer", pa.string()), ("annotator_id", pa.string()),
        ("reference_role", pa.string()),
        ("concept_ids", pa.list_(pa.string())),
        ("concept_labels_de", pa.list_(pa.string())),
        ("annotation_status", pa.string()), ("recovered", pa.int64()),
        ("unmapped_model_suggestions", pa.string()),
        ("policy_version", pa.string()), ("vocabulary_version", pa.string()),
        ("input_variant_id", pa.string()), ("input_fields_used", pa.string()),
        ("run_manifest_sha256", pa.string()), ("adjudication_status", pa.string()),
    ])
    (OUT / "data/annotations").mkdir(parents=True, exist_ok=True)
    dst = OUT / "data/annotations/all-00000-of-00001.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), dst)
    (OUT / "manifests").mkdir(parents=True, exist_ok=True)
    used = sorted({cid for values in df.concept_ids for cid in values})
    zero = sorted(set(label2id.values()) - set(used))
    stats = {
        "rows": len(df),
        "status_counts": df.annotation_status.value_counts().to_dict(),
        "tag_assignments": int(df.concept_ids.map(len).sum()),
        "used_concepts": len(used),
        "zero_assigned_concepts": zero,
    }
    annotation_manifest = {
        "canonical_normalized_csv": str(
            SRC.relative_to(ROOT) if SRC.is_relative_to(ROOT) else SRC
        ),
        "canonical_manifest_sha256": run_manifest_sha,
        "producer": portable_producer_paths(manifest.get("producer")),
        "policy_version": POLICY_VERSION,
        "vocabulary_version": VOCAB_VERSION,
        "input_sha256": {
            "normalized_csv": hashlib.sha256(SRC.read_bytes()).hexdigest(),
            "manifest": hashlib.sha256(MAN.read_bytes()).hexdigest(),
        },
        "annotation_statistics": stats,
    }
    (OUT / "manifests/annotation_run_manifest.json").write_text(
        json.dumps(annotation_manifest, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "manifests/model_generated_stats.txt").write_text(
        "\n".join([
            f"rows: {stats['rows']}",
            f"status counts: {stats['status_counts']}",
            f"tag assignments: {stats['tag_assignments']}",
            f"distinct concepts used: {stats['used_concepts']}/{len(label2id)}",
            f"zero-tag concepts: {len(zero)}",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"annotations: {len(df)} model_generated rows -> {dst}")
    print("  status:", df.annotation_status.value_counts().to_dict())
    print("  authenticated against manifest; per-row id<->label mapping and "
          "canonical ordering asserted")


if __name__ == "__main__":
    main()
