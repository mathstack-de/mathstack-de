#!/usr/bin/env python3
"""Build the EXPERT_REFERENCE and SPLITS release tables.

expert_reference: the frozen 200-row single-expert reference, one row per
question: sample (probability/diagnostic), design weight, v1.1 concept
ids and labels, expert difficulty, and documented provenance.

splits: the frozen near_duplicate_group-safe partition produced by baselines/build_data.py
(train/dev/test_probability/test_diagnostic/excluded_near_duplicate), one row per
question with its near_duplicate_group id. The paper's leakage guarantee ("no expert
question, variant, or near_duplicate_group relative in train/dev") is asserted here again.

Usage: python build_expert_reference.py
"""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = HERE / "out"
EXPERT = ROOT / "not_included/expert_reference.csv"
GBERT_TABLE = ROOT / "baselines/data/concept_tagging.csv"
SPLIT_MANIFEST = ROOT / "baselines/splits/split_manifest.json"
DIFFICULTY = {"1": "easy", "2": "medium", "3": "hard"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    id2label = json.loads((OUT / "vocabulary/id2label.json").read_text())
    expert = pd.read_csv(EXPERT, encoding="utf-8-sig", keep_default_na=False)
    assert len(expert) == 200 and expert["rc_id"].is_unique
    table = pd.read_csv(GBERT_TABLE, keep_default_na=False)
    assert len(table) == 2403 and table["question_id"].is_unique
    split_of = dict(zip(table["question_id"], table["split"]))
    family_of = dict(zip(table["question_id"], table["near_duplicate_group_id"]))

    rows = []
    for r in expert.to_dict("records"):
        ids = [i for i in r["concept_ids"].split("|") if i]
        for cid in ids:
            assert cid in id2label, f"unknown concept id {cid}"
        sample = r["sample"]
        assert split_of[r["rc_id"]] == (
            "test_probability" if sample == "probability_sample" else "test_diagnostic")
        rows.append({
            "rc_id": r["rc_id"], "name": r["name"], "source_bank_category": r["source_bank_category"],
            "sample": sample,
            "design_weight": float(r["design_weight"]) if r["design_weight"] else None,
            "concept_ids": ids,
            "concept_labels_de": [id2label[c] for c in ids],
            "expert_difficulty": DIFFICULTY.get(str(r["difficulty_1_2_3"]), ""),
            "annotator_id": r["annotator_id"],
            "policy_version": r["policy_version"],
            "vocabulary_version": r["vocabulary_version"],
        })
    ref = pa.Table.from_pylist(rows)
    (OUT / "data/expert_reference").mkdir(parents=True, exist_ok=True)
    pq.write_table(ref, OUT / "data/expert_reference/all-00000-of-00001.parquet")

    # splits table + leakage re-assertion
    test_ids = set(expert["rc_id"])
    train_dev = set(table.loc[table["split"].isin(["train", "dev"]), "question_id"])
    assert not (test_ids & train_dev)
    test_fams = {family_of[rc] for rc in test_ids}
    assert not (test_fams & {family_of[rc] for rc in train_dev})
    splits = pa.Table.from_pylist([
        {"rc_id": rc, "near_duplicate_group_id": family_of[rc], "split": split_of[rc]}
        for rc in sorted(split_of)])
    (OUT / "data/splits").mkdir(parents=True, exist_ok=True)
    pq.write_table(splits, OUT / "data/splits/all-00000-of-00001.parquet")

    manifest = {
        "expert_rows": len(rows),
        "samples": {"probability_sample": 140, "diagnostic_sample": 60},
        "splits_rows": len(split_of),
        "split_counts": table["split"].value_counts().to_dict(),
        "leakage": "0 row overlap, 0 near_duplicate_group overlap (re-asserted at build)",
        "sha256": {"expert_csv": sha256(EXPERT), "gbert_table": sha256(GBERT_TABLE),
                   "split_manifest": sha256(SPLIT_MANIFEST)},
    }
    (OUT / "data/expert_reference/build_manifest.json").write_text(
        json.dumps(manifest, indent=1))
    print(f"expert_reference: 200 rows; splits: {manifest['split_counts']}")


if __name__ == "__main__":
    main()
