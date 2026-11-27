#!/usr/bin/env python3
"""Build the GBERT concept-tagging modeling table, near_duplicate_group-safe splits, audits.

Deterministic: same inputs + seed -> byte-identical outputs. Fails closed on any count or
boundary violation. No network, no model calls.
"""
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
SPLITS = HERE / "splits"
SEED = 20260723
DEV_FRACTION = 0.15

MODEL_GENERATED_DIR = ROOT / "not_included/model_generated_labels_v1_1"
INPUT_TABLE = MODEL_GENERATED_DIR / "raw_preprocessed_dataframe.csv"
MODEL_GENERATED_CSV = MODEL_GENERATED_DIR / "model_generated_labels_v1_1.csv"
EXPERT_CSV = ROOT / "not_included/expert_reference.csv"
VOCAB_YAML = ROOT / "concept_vocabulary.v1_1.yaml"
QUARANTINE = ROOT / "not_included/expert_reference_source.csv"

BOUNDARY_MARKERS = ("<prt", "questionvariables", "samplesolution", "deployedseed",
                    "META-START", "Musterlösung erstellt", "✍")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def active_concept_ids():
    ids = re.findall(r"\{id:\s*([A-Z-]+\.\d+)", VOCAB_YAML.read_text(encoding="utf-8"))
    seen = sorted(set(ids))
    if len(seen) != 271:
        raise SystemExit(f"expected 271 active v1.1 concepts, parsed {len(seen)}")
    return seen


def name_stem(name):
    s = name.lower()
    s = re.sub(r"\(.*?\)", " ", s)                    # parenthesized tails
    s = re.sub(r"[\d]+", " ", s)                      # numbering
    s = re.sub(r"\b(i{1,3}|iv|v|vi{0,3}|[a-e])\b", " ", s)  # roman/letter variants
    s = re.sub(r"[^a-zäöüß]+", " ", s)
    return " ".join(s.split())


def norm_text(text):
    return re.sub(r"\s+", " ", (text or "").lower())[:4000]


def shingles(text, n=3):
    t = re.sub(r"[^a-z0-9äöüß]", "", (text or "").lower())
    return {t[i:i + n] for i in range(len(t) - n + 1)} if len(t) >= n else {t}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def main():
    DATA.mkdir(exist_ok=True)
    SPLITS.mkdir(exist_ok=True)
    concept_ids = active_concept_ids()
    csv.field_size_limit(10 ** 8)

    # ---- inputs ----
    inputs = {}
    with open(INPUT_TABLE, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rc = row["idnumber"].strip()
            if not rc.startswith("rc-"):
                continue
            text = (row["questiontext_maxima_evaluated_no_html_syntax"] or "").strip()
            opts = (row["answeroptions"] or "").strip()
            joined = text + ("\n\nAntwortoptionen:\n" + opts if opts else "")
            inputs[rc] = {"input_text": joined, "category": row.get("category", "")}
    if len(inputs) != 2403:
        raise SystemExit(f"expected 2403 input rows, got {len(inputs)}")

    model_generated = {}
    model_generated_meta = {}
    for row in csv.DictReader(open(MODEL_GENERATED_CSV, encoding="utf-8-sig")):
        ids = [i for i in (row["concept_ids"] or "").split("|") if i]
        unknown = set(ids) - set(concept_ids)
        if unknown:
            raise SystemExit(f"model_generated uses unknown concept ids {unknown} on {row['rc_id']}")
        model_generated[row["rc_id"]] = ids
        model_generated_meta[row["rc_id"]] = {"name": row["name"], "status": row["status"]}
    if len(model_generated) != 2403:
        raise SystemExit(f"expected 2403 model_generated rows, got {len(model_generated)}")

    expert = {}
    for row in csv.DictReader(open(EXPERT_CSV, encoding="utf-8-sig")):
        ids = [i for i in (row["concept_ids"] or "").split("|") if i]
        unknown = set(ids) - set(concept_ids)
        if unknown:
            raise SystemExit(f"expert uses unknown concept ids {unknown} on {row['rc_id']}")
        expert[row["rc_id"]] = {
            "labels": ids,
            "sample": row["sample"],
            "design_weight": float(row["design_weight"]) if row.get("design_weight") else None,
            "difficulty": row.get("difficulty_1_2_3", ""),
            "source_bank_category": row.get("source_bank_category", ""),
        }
    if len(expert) != 200:
        raise SystemExit(f"expected 200 expert rows, got {len(expert)}")
    quarantine_ids = {r["rc_id"] for r in csv.DictReader(open(QUARANTINE, encoding="utf-8-sig"))}
    if quarantine_ids != set(expert):
        raise SystemExit("quarantine list and expert reference disagree")

    # ---- information-boundary scan on every model input ----
    boundary_hits = []
    for rc, row in inputs.items():
        low = row["input_text"].lower()
        for marker in BOUNDARY_MARKERS:
            if marker.lower() in low:
                boundary_hits.append((rc, marker))
    if boundary_hits:
        raise SystemExit(f"information-boundary violations in input text: {boundary_hits[:5]}")

    # ---- near_duplicate_groups: name-stem grouping + near-duplicate merge ----
    uf = UnionFind()
    stem_groups = defaultdict(list)
    for rc in inputs:
        stem = name_stem(model_generated_meta[rc]["name"]) or rc
        stem_groups[stem].append(rc)
    for members in stem_groups.values():
        for other in members[1:]:
            uf.union(members[0], other)
    # near-duplicate pass: identical normalized text always merges; high-jaccard
    # merges within same first-120-char bucket (cheap deterministic banding)
    text_norm = {rc: norm_text(inputs[rc]["input_text"]) for rc in inputs}
    by_exact = defaultdict(list)
    for rc, t in text_norm.items():
        by_exact[t].append(rc)
    for members in by_exact.values():
        for other in members[1:]:
            uf.union(members[0], other)
    bucket = defaultdict(list)
    for rc, t in text_norm.items():
        bucket[t[:120]].append(rc)
    merges = 0
    for members in bucket.values():
        if len(members) < 2 or len(members) > 40:
            continue
        sh = {rc: shingles(text_norm[rc]) for rc in members}
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if uf.find(a) != uf.find(b) and jaccard(sh[a], sh[b]) >= 0.9:
                    uf.union(a, b)
                    merges += 1
    # exhaustive near-duplicate pass against the 200 test questions: any corpus
    # row >= 0.9 Jaccard to a test row joins that test row's near_duplicate_group (and is
    # therefore excluded from train/dev). Names and prefixes can differ, so
    # this pass is unbanded.
    test_shingle = {rc: shingles(text_norm[rc]) for rc in expert}
    for rc in inputs:
        if rc in expert:
            continue
        sh = shingles(text_norm[rc])
        for trc, tsh in test_shingle.items():
            if jaccard(sh, tsh) >= 0.9:
                uf.union(rc, trc)
                merges += 1
                break
    family_of = {rc: uf.find(rc) for rc in inputs}
    family_index = {root: f"fam-{i:04d}" for i, root in
                    enumerate(sorted(set(family_of.values())))}
    family_of = {rc: family_index[root] for rc, root in family_of.items()}

    # ---- splits ----
    forbidden_families = {family_of[rc] for rc in expert}
    test_rows = set(expert)
    remaining = [rc for rc in inputs
                 if rc not in test_rows and family_of[rc] not in forbidden_families]
    excluded_family_rows = [rc for rc in inputs
                            if rc not in test_rows and family_of[rc] in forbidden_families]
    fams = sorted({family_of[rc] for rc in remaining})
    import random
    rng = random.Random(SEED)
    rng.shuffle(fams)
    rows_per_fam = Counter(family_of[rc] for rc in remaining)
    target_dev = round(DEV_FRACTION * len(remaining))
    dev_fams, ndev = set(), 0
    for fam in fams:
        if ndev >= target_dev:
            break
        dev_fams.add(fam)
        ndev += rows_per_fam[fam]
    split_of = {}
    for rc in inputs:
        if rc in test_rows:
            split_of[rc] = ("test_probability" if expert[rc]["sample"] == "probability_sample"
                            else "test_diagnostic")
        elif family_of[rc] in forbidden_families:
            split_of[rc] = "excluded_near_duplicate"
        else:
            split_of[rc] = "dev" if family_of[rc] in dev_fams else "train"

    # ---- leakage checks ----
    train_dev = {rc for rc in inputs if split_of[rc] in ("train", "dev")}
    assert not (train_dev & test_rows), "row leakage"
    assert not ({family_of[rc] for rc in train_dev} & forbidden_families), "near_duplicate_group leakage"
    near_dups = []
    test_sh = {rc: shingles(text_norm[rc]) for rc in test_rows}
    for rc in sorted(train_dev):
        sh = shingles(text_norm[rc])
        for trc, tsh in test_sh.items():
            if jaccard(sh, tsh) >= 0.9:
                near_dups.append((rc, trc, round(jaccard(sh, tsh), 3)))
    if near_dups:
        raise SystemExit(f"near-duplicate leakage train/dev vs test: {near_dups[:5]}")

    # ---- modeling table ----
    records = []
    for rc in sorted(inputs):
        e = expert.get(rc)
        records.append({
            "question_id": rc,
            "near_duplicate_group_id": family_of[rc],
            "split": split_of[rc],
            "input_text": inputs[rc]["input_text"],
            "labels_model_generated": "|".join(model_generated[rc]),
            "labels_expert": "|".join(e["labels"]) if e else "",
            "sample": e["sample"] if e else "",
            "design_weight": e["design_weight"] if e else None,
            "expert_difficulty": e["difficulty"] if e else "",
            "source_bank_category": (e["source_bank_category"] if e else inputs[rc]["category"].split("/")[-1]),
            "model_generated_status": model_generated_meta[rc]["status"],
        })
    df = pd.DataFrame(records)
    table_path = DATA / "concept_tagging.parquet"
    try:
        df.to_parquet(table_path, index=False)
    except Exception:
        table_path = DATA / "concept_tagging.csv"
        df.to_csv(table_path, index=False)

    (DATA / "label_space.json").write_text(json.dumps(
        {"concept_ids": concept_ids, "order": "lexicographic", "n": len(concept_ids)},
        indent=1))

    for name in ("train", "dev", "test_probability", "test_diagnostic", "excluded_near_duplicate"):
        ids = sorted(rc for rc in inputs if split_of[rc] == name)
        (SPLITS / f"{name}_ids.txt").write_text("\n".join(ids) + "\n")

    counts = Counter(split_of.values())
    support = Counter()
    for rc in inputs:
        if split_of[rc] == "train":
            for cid in model_generated[rc]:
                support[cid] += 1
    buckets = Counter()
    for cid in concept_ids:
        s = support.get(cid, 0)
        buckets["0" if s == 0 else "1-4" if s < 5 else "5-19" if s < 20 else "20+"] += 1

    manifest = {
        "created_by": "baselines/build_data.py",
        "random_seed": SEED,
        "counts": dict(counts),
        "n_families": len(family_index),
        "excluded_near_duplicate_n": len(forbidden_families),
        "excluded_family_rows": len(excluded_family_rows),
        "near_dup_merges": merges,
        "train_support_buckets": dict(buckets),
        "inputs_sha256": {
            "input_table": sha256(INPUT_TABLE), "model_generated": sha256(MODEL_GENERATED_CSV),
            "expert": sha256(EXPERT_CSV), "vocab": sha256(VOCAB_YAML),
            "quarantine": sha256(QUARANTINE),
        },
        "outputs_sha256": {
            "table": sha256(table_path),
            **{f"{n}_ids": sha256(SPLITS / f"{n}_ids.txt") for n in
               ("train", "dev", "test_probability", "test_diagnostic", "excluded_near_duplicate")},
        },
        "leakage_checks": ["row_overlap=0", "family_overlap=0",
                           "near_dup_jaccard>=0.9_train_dev_vs_test=0"],
    }
    (SPLITS / "split_manifest.json").write_text(json.dumps(manifest, indent=1))

    audit = [
        "# GBERT data audit", "",
        f"rows: {len(inputs)} | near_duplicate_groups: {len(family_index)} "
        f"(near-dup merges: {merges})",
        f"splits: {dict(counts)}",
        f"excluded near-duplicate groups: {len(forbidden_families)} "
        f"(excluding {len(excluded_family_rows)} non-test relative rows from train/dev)",
        f"zero-label (valid_empty) rows: "
        f"{sum(1 for rc in inputs if not model_generated[rc])}",
        f"train label support buckets (of 271 concepts): {dict(buckets)}",
        f"labels/question (train): mean "
        f"{sum(len(model_generated[rc]) for rc in inputs if split_of[rc]=='train') / max(counts['train'],1):.2f}",
        "", "information-boundary scan: CLEAN (no tans/PRT/qv/meta markers in any input)",
    ]
    (DATA / "data_audit.md").write_text("\n".join(audit) + "\n")
    (DATA / "leakage_report.md").write_text(
        "# Leakage report\n\nNo expert-reference question, template variant, or "
        "near-duplicate question appears in train or dev:\n"
        f"- question-ID overlap: 0\n- near-duplicate-group ID overlap: 0 "
        f"({len(forbidden_families)} excluded near-duplicate groups; "
        f"{len(excluded_family_rows)} relative rows excluded)\n"
        "- normalized-text near-duplicate (3-gram Jaccard >= 0.9) between "
        "train+dev and test: 0 pairs\n")
    print(f"table -> {table_path.name} | splits: {dict(counts)} | "
          f"near_duplicate_groups {len(family_index)} | support {dict(buckets)}")


if __name__ == "__main__":
    main()
