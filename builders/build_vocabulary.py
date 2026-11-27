#!/usr/bin/env python3
"""Build the release vocabulary artifacts from the frozen concept dictionary.

All concept IDs exist in the frozen v1.1 271-label mapping; multi-hot
vectors are length 271.

Outputs (out/vocabulary/):
  label2id.json      canonical German label -> stable concept id
  id2label.json      stable concept id -> canonical German label
  labels_order.json  the FROZEN multi-hot ordering (sorted by concept id);
                     concept_multi_hot[i] corresponds to labels_order[i]
  concept_vocabulary.v1_1.yaml  release vocabulary containing stable IDs, German
                           labels, English reference translations, concept
                           types, approved definitions, and cross-references
  ANNOTATION_POLICY_v1.1.md  released annotation policy

`proposed: true` concepts and internal working notes are excluded. The public
artifact contains the reviewed v1.1 vocabulary and policy.
"""
import json
import shutil
from pathlib import Path

import yaml

HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = HERE / "out/vocabulary"

VOCAB = ROOT / "concept_vocabulary.v1_1.yaml"
POLICY = ROOT / "ANNOTATION_POLICY_v1.1.md"
VOCAB_VERSION = "v1.1_2026-07"
PUBLIC_FIELDS = ("id", "de", "en", "type", "definition", "see_also")
KNOWN_AUXILIARY_FIELDS = {"note", "proposed"}


def flatten(d):
    for code, concepts in d.items():
        for c in concepts:
            if isinstance(c, dict) and not c.get("proposed"):
                yield c


def main():
    data = yaml.safe_load(VOCAB.read_text(encoding="utf-8"))
    concepts = sorted(flatten(data), key=lambda c: c["id"])
    assert len(concepts) == 271, f"expected 271 active concepts, got {len(concepts)}"
    ids = [c["id"] for c in concepts]
    labels = [c["de"] for c in concepts]
    assert len(set(ids)) == 271, "concept ids not unique"
    assert len(set(labels)) == 271, "German labels not unique"

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "label2id.json").write_text(
        json.dumps(dict(zip(labels, ids)), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "id2label.json").write_text(
        json.dumps(dict(zip(ids, labels)), ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "labels_order.json").write_text(
        json.dumps({"vocabulary_version": VOCAB_VERSION, "n_labels": 271,
                    "order": ids}, ensure_ascii=False, indent=1), encoding="utf-8")
    source_fields = {key for rows in data.values() for row in rows
                     for key in row}
    unknown_fields = source_fields - set(PUBLIC_FIELDS) - KNOWN_AUXILIARY_FIELDS
    assert not unknown_fields, (
        f"vocabulary fields outside the release fields: "
        f"{sorted(unknown_fields)}")
    public_data = {
        group: [
            {key: concept[key] for key in PUBLIC_FIELDS if key in concept}
            for concept in group_concepts
            if not concept.get("proposed")
        ]
        for group, group_concepts in data.items()
    }
    public_count = sum(len(group) for group in public_data.values())
    assert public_count == 271, public_count
    header = (
        "# MathStack-DE concept vocabulary.\n"
        f"# version: {VOCAB_VERSION}\n"
        "# Release fields: stable ids, German labels, English reference "
        "translations, concept types, approved definitions, and "
        "cross-references.\n"
    )
    (OUT / VOCAB.name).write_text(
        header + yaml.safe_dump(public_data, sort_keys=False,
                                allow_unicode=True, width=88),
        encoding="utf-8")
    if POLICY.exists():
        shutil.copy2(POLICY, OUT / POLICY.name)
    print(f"vocabulary: 271 active concepts ({VOCAB_VERSION}) -> {OUT}")


if __name__ == "__main__":
    main()
