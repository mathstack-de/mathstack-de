#!/usr/bin/env python3
"""Validation of the corpus tables.

The default mode validates the tables that can currently be built and reports
what a complete build still lacks. ``--final`` additionally requires the
public/key-bearing solving views and closed asset decisions.

Run:
  python validate_release.py
  python validate_release.py --final
"""
import argparse
import hashlib
import json
import re
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from author_credits import QUESTION_AUTHOR_CREDITS

HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = HERE / "out"

FAILURES = []


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--final",
        action="store_true",
        help="enforce all final checks, not only the buildable subset",
    )
    return parser.parse_args()


def check(name, cond, detail=""):
    status = "ok" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source_freshness():
    """Reject generated source tables whose consumed inputs have changed."""
    manifest_path = OUT / "manifests/source_files.json"
    if not manifest_path.exists():
        check("source provenance manifest present", False, str(manifest_path))
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_paths = manifest.get("input_paths")
    expected = manifest.get("inputs_sha256")
    check("source provenance records input paths", isinstance(input_paths, dict))
    check("source provenance records input hashes", isinstance(expected, dict))
    if not isinstance(input_paths, dict) or not isinstance(expected, dict):
        return

    missing_keys = sorted(set(expected) - set(input_paths))
    extra_keys = sorted(set(input_paths) - set(expected))
    check("source provenance path/hash keys agree",
          not missing_keys and not extra_keys,
          f"missing paths={missing_keys}; missing hashes={extra_keys}")

    stale = []
    missing = []
    escaping = []
    root = ROOT.resolve()
    for key in sorted(set(input_paths) & set(expected)):
        path = (ROOT / input_paths[key]).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            escaping.append(f"{key}={input_paths[key]}")
            continue
        if not path.is_file():
            missing.append(f"{key}={input_paths[key]}")
        elif sha256_file(path) != expected[key]:
            stale.append(f"{key}={input_paths[key]}")

    check("source provenance paths stay inside repository", not escaping,
          ", ".join(escaping))
    check("all source inputs still exist", not missing, ", ".join(missing))
    check("generated source table matches current inputs", not stale,
          ", ".join(stale))


PUBLIC_SOLVING_COLUMNS = {
    "dataset_version", "schema_version", "variant_id", "rc_id", "seed",
    "seed_origin", "is_author_deployed", "question_text_rendered",
    "answer_options_rendered", "response_schema_json",
    "instantiation_status", "engine_build", "render_sha256",
}
KEY_ONLY_COLUMNS = {
    "expected_responses", "generalfeedback_rendered", "questionvariables",
    "stack_prts_json", "roundtrip_score", "roundtrip_ok", "roundtrip_form",
}


def check_solving_views(source):
    """Invariants for the paired answer-free/key-bearing views."""
    pub_path = OUT / "data/solving_public/all-00000-of-00001.parquet"
    keys_path = OUT / "data/solving_with_keys/all-00000-of-00001.parquet"
    if not (pub_path.exists() and keys_path.exists()):
        print("  [PENDING] solving views: not built")
        return
    pub = pq.read_table(pub_path).to_pandas()
    keys = pq.read_table(keys_path).to_pandas()
    gradable = source[(source.question_type == "stack")
                      & source.is_auto_gradable]
    check("solving views cover every auto-gradable STACK question",
          len(pub) == len(gradable)
          and set(pub.rc_id) == set(gradable.rc_id),
          f"{len(pub)} rows vs {len(gradable)} gradable")
    check("variant_id unique and identical across views",
          pub.variant_id.is_unique
          and set(pub.variant_id) == set(keys.variant_id))
    check("solving views use solving_v2",
          set(pub.schema_version) == {"solving_v2"}
          and set(keys.schema_version) == {"solving_v2"})
    check("public view carries no key-bearing columns",
          set(pub.columns) == PUBLIC_SOLVING_COLUMNS
          and not (KEY_ONLY_COLUMNS & set(pub.columns)),
          str(sorted(set(pub.columns) ^ PUBLIC_SOLVING_COLUMNS)))
    check("key view adds exactly the key-bearing columns",
          set(keys.columns) == PUBLIC_SOLVING_COLUMNS | KEY_ONLY_COLUMNS)
    merged = pub.merge(keys, on="variant_id", suffixes=("_p", "_k"))
    check("rendered question text identical across views",
          (merged.question_text_rendered_p
           == merged.question_text_rendered_k).all())
    check("render integrity hashes identical across views",
          (merged.render_sha256_p == merged.render_sha256_k).all())
    check("no sealed questionnote column in either view",
          "questionnote" not in pub.columns
          and "questionnote" not in keys.columns)
    check("every key row carries evaluated teacher responses",
          keys.expected_responses.map(
              lambda v: isinstance(v, str) and v not in ("", "{}")).all())
    source_prts = gradable.set_index("rc_id").stack_prts_json
    key_prts = keys.set_index("rc_id").stack_prts_json
    check("key view preserves source stack_prts_v2 records",
          key_prts.equals(source_prts.loc[key_prts.index])
          and keys.stack_prts_json.map(
              lambda raw: json.loads(raw)["schema"] == "stack_prts_v2"
          ).all())
    def flat_values(blob):
        for value in json.loads(blob).values():
            if isinstance(value, dict):
                yield from value.values()
            else:
                yield value

    check("public rendered text never embeds a teacher answer verbatim",
          not merged.apply(
              lambda r: any(
                  len(str(v)) >= 8 and str(v) in r.question_text_rendered_p
                  for v in flat_values(r.expected_responses)),
              axis=1).any())
    manifest_path = OUT / "manifests/solving_build_manifest.json"
    check("solving build manifest present", manifest_path.exists())
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        check("solving manifest matches view row count",
              manifest.get("rows") == len(pub))
        expected_xml_digests = {
            path.name: sha256_file(path)
            for path in (
                ROOT / "not_included/quiz-Math1-Math2.xml",
                ROOT / "not_included/quiz-Numeric.xml",
            )
        }
        check("solving manifest pins the corpus XML digests",
              manifest.get("source_xml_sha256") == expected_xml_digests)
        source_path = OUT / "data/source/all-00000-of-00001.parquet"
        check("solving manifest pins source_v2 table bytes",
              manifest.get("source_schema_version") == "source_v2"
              and manifest.get("source_table_sha256")
              == hashlib.sha256(source_path.read_bytes()).hexdigest())
    log_path = OUT / "manifests/corrections_log.json"
    check("corrections log present", log_path.exists())
    if log_path.exists():
        log = json.loads(log_path.read_text())
        check("corrections log records six defects on five questions",
              log.get("defect_total") == 6
              and log.get("questions_affected") == 5
              and len(log.get("entries", [])) == 6)




def main(final=False):
    FAILURES.clear()
    print("source provenance/freshness:")
    check_source_freshness()

    src = pq.read_table(OUT / "data/source/all-00000-of-00001.parquet")
    df = src.to_pandas()

    print("source counts:")
    check("2,403 total questions", len(df) == 2403, str(len(df)))
    check("1,604 STACK", (df.question_type == "stack").sum() == 1604)
    check("799 non-STACK", (df.question_type != "stack").sum() == 799)
    check("1,574 substantive human GFs (4 footer-only empties excluded)",
          ((df.gf_provenance == "human") & df.has_generalfeedback).sum() == 1574)
    generated_solution = df[df.gf_provenance.str.startswith("ai_generated", na=False)]
    check(
        "111 expert-approved generated worked solution rows included with explicit provenance",
        len(generated_solution) == 111
        and set(generated_solution.gf_author_code) == {"AI"}
        and generated_solution.gf_verification_status.notna().all(),
        f"{len(generated_solution)} rows",
    )
    check(
        "1,685 total substantive GFs",
        df.has_generalfeedback.sum() == 1685,
        str(df.has_generalfeedback.sum()),
    )

    print("generated worked-solution release table:")
    generated_path = (
        OUT / "data/generated_worked_solutions/all-00000-of-00001.parquet"
    )
    generated_manifest_path = (
        OUT / "manifests/generated_worked_solutions_manifest.json"
    )
    if generated_path.exists() and generated_manifest_path.exists():
        generated = pq.read_table(generated_path).to_pandas()
        generated_manifest = json.loads(
            generated_manifest_path.read_text(encoding="utf-8")
        )
        check(
            "252 generated solutions released in explicit evidence tiers",
            len(generated) == 252
            and generated.rc_id.is_unique
            and generated.release_tier.value_counts().to_dict()
            == {
                "machine_checked_not_expert_reviewed": 141,
                "expert_approved": 111,
            },
            str(generated.release_tier.value_counts().to_dict()),
        )
        check(
            "generated-solution rows retain AI authorship and CC BY-SA 4.0",
            set(generated.gf_author_code) == {"AI"}
            and set(generated.content_license) == {"CC-BY-SA-4.0"},
        )
        check(
            "all released generated solutions belong to the annotation context",
            generated.annotation_context_used.all()
            and generated.generation_candidate_full_credit.all()
            and set(generated.rc_id) <= set(df.rc_id),
        )
        machine = generated[
            generated.release_tier == "machine_checked_not_expert_reviewed"
        ]
        expert_generated = generated[
            generated.release_tier == "expert_approved"
        ]
        check(
            "141 machine-only rows satisfy the declared release criteria",
            len(machine) == 141
            and machine.generation_candidate_presentation_clean.all()
            and machine.generation_candidate_result_match.all()
            and (machine.generation_links_flagged == 0).all()
            and not set(machine.rc_id) & set(df[df.has_generalfeedback].rc_id),
        )
        check(
            "111 expert-approved rows satisfy the expert-approval criteria",
            len(expert_generated) == 111
            and set(expert_generated.rc_id) == set(generated_solution.rc_id),
        )
        check(
            "generated-solution manifest pins the 252/255 boundary",
            generated_manifest.get("rows") == 252
            and generated_manifest.get("annotation_context_full_credit_total")
            == 255
            and len(generated_manifest.get("excluded_full_credit_rows", [])) == 3
            and generated_manifest.get("output_sha256")
            == sha256_file(generated_path),
        )
    else:
        check(
            "generated worked-solution table and manifest present",
            False,
            f"{generated_path.exists()}/{generated_manifest_path.exists()}",
        )

    print("identity:")
    check("2,403 unique valid rc_ids",
          df.rc_id.nunique() == 2403 and
          df.rc_id.str.match(r"rc-[0-9a-f-]{36}$").all())
    check("content_sha256 present and unique",
          df.content_sha256.notna().all() and df.content_sha256.nunique() == 2403)

    print("authorship:")
    check("question_author_code coverage",
          df.question_author_code.notna().all(),
          f"{df.question_author_code.isna().sum()} missing")
    check(
        "question_author_credit expands every source-bank code",
        df.question_author_credit.notna().all()
        and all(
            credit == QUESTION_AUTHOR_CREDITS.get(code)
            for code, credit in zip(
                df.question_author_code, df.question_author_credit, strict=True
            )
        ),
    )
    check(
        "A3 rows carry the joint credit",
        (
            df.loc[df.question_author_code == "A3", "question_author_credit"]
            == QUESTION_AUTHOR_CREDITS["A3"]
        ).all()
        and (df.question_author_code == "A3").sum() == 860,
    )
    check(
        "independently authored replacement carries project credit",
        (df.question_author_code == "A0").sum() == 1
        and (
            df.loc[
                df.question_author_code == "A0",
                "question_author_credit",
            ]
            == QUESTION_AUTHOR_CREDITS["A0"]
        ).all(),
    )
    gf_rows = df[df.has_generalfeedback]
    check("gf_author_code present on GF rows (NN allowed, silent-missing not)",
          gf_rows.gf_author_code.notna().all(),
          f"{gf_rows.gf_author_code.isna().sum()} missing")
    check("no gf_author_code on GF-less rows",
          df[~df.has_generalfeedback].gf_author_code.isna().all())
    attribution = pq.read_table(OUT / "data/attribution/all-00000-of-00001.parquet")
    import pyarrow as pa
    check("1,576 migrated attribution records", len(attribution) == 1576,
          str(len(attribution)))
    check("attribution table uses explicit string fields",
          all(pa.types.is_string(field.type) for field in attribution.schema),
          str(attribution.schema))

    print("STACK structure:")
    stack = df[df.question_type == "stack"]
    check("source table uses source_v2", set(df.schema_version) == {"source_v2"})
    n_inputs = stack.stack_inputs.map(lambda x: len(x) if x is not None else 0)
    check("582 multi-input STACK questions preserved", (n_inputs > 1).sum() == 582,
          str((n_inputs > 1).sum()))
    check("max 24 inputs question survives", n_inputs.max() == 24, str(n_inputs.max()))
    check("every STACK question has inputs parsed", (n_inputs > 0).all(),
          f"{(n_inputs == 0).sum()} without")
    noprt = stack[stack.stack_prts_json.isna()]
    check("PRT-less STACK limited to the 1 documented free-text question",
          list(noprt.name.str[:30]) in ([], ["NUM_Verfahren (rand): Freitext"]),
          str(list(noprt.name)))
    contracts = [json.loads(raw) for raw in stack.stack_prts_json.dropna()]
    check("source uses complete stack_prts_v2 records",
          all(contract.get("schema") == "stack_prts_v2"
              for contract in contracts))
    prts = [prt for contract in contracts for prt in contract["prts"]]
    nodes = [node for prt in prts for node in prt["nodes"]]
    check("all 2,690 PRTs preserved", len(prts) == 2690, str(len(prts)))
    check("all 3,469 PRT nodes preserved", len(nodes) == 3469,
          str(len(nodes)))
    check("PRT branching and score modes are represented",
          all("truenextnode" in node and "falsenextnode" in node
              and "truescoremode" in node and "falsescoremode" in node
              for node in nodes))

    print("seeds (int64 round-trip):")
    seed_field = src.schema.field("deployed_seeds").type
    check("deployed_seeds is list<int64>",
          pa.types.is_list(seed_field) and pa.types.is_int64(seed_field.value_type),
          str(seed_field))
    mx = max((max(s) for s in df.deployed_seeds if len(s)), default=0)
    check("max seed 8,898,666,092 survives", mx == 8898666092, str(mx))

    print("assets:")
    adf = pq.read_table(OUT / "assets/assets.parquet").to_pandas()
    rdf = pq.read_table(OUT / "assets/asset_references.parquet").to_pandas()
    check("184 unique payloads", len(adf) == 184, str(len(adf)))
    check("233 references", len(rdf) == 233, str(len(rdf)))
    check("all references resolve",
          rdf.asset_sha256.isin(adf.asset_sha256).all())
    check("every payload has a release-decision field",
          adf.release_decision.notna().all())
    pending_assets = int(
        adf.release_decision.astype("string").str.lower().eq("pending").sum()
    )
    if final:
        check(
            "all asset release decisions are final",
            pending_assets == 0,
            f"{pending_assets}/{len(adf)} still pending",
        )
    else:
        print(
            "  [PENDING] asset release decisions: "
            f"{pending_assets}/{len(adf)} still pending"
        )

    print("vocabulary:")
    l2i = json.loads((OUT / "vocabulary/label2id.json").read_text(encoding="utf-8"))
    order = json.loads((OUT / "vocabulary/labels_order.json").read_text(encoding="utf-8"))
    check("271 v1.1 labels", len(l2i) == 271 and order["n_labels"] == 271)
    check("vocabulary version is v1.1_2026-07",
          order["vocabulary_version"] == "v1.1_2026-07")
    check("multi-hot order == sorted unique ids",
          order["order"] == sorted(set(l2i.values())))

    print("expert-reference manifest:")
    g = pd.read_csv(OUT / "manifests/expert_reference_manifest.csv")
    check("140 probability_sample + 60 diagnostic_sample",
          ((g.sample == "probability_sample").sum(),
           (g.sample == "diagnostic_sample").sum()) == (140, 60))
    rt = g[g.sample == "probability_sample"]
    check("weights present on every probability_sample row", rt.design_weight.notna().all())
    check("weighted frame reproduces 1,574",
          abs(rt.design_weight.sum() - 1574) < 1e-6, f"{rt.design_weight.sum():.4f}")
    check("no weights on diagnostic sample",
          g[g.sample == "diagnostic_sample"].design_weight.isna().all())
    check("expert-reference rc_ids exist in source", g.rc_id.isin(df.rc_id).all())

    print("twin pairs:")
    twins = pd.read_csv(ROOT / "not_included/legacyhash_twin_pairs.csv", encoding="utf-8-sig")
    ids = set(twins.rc_id_a) | set(twins.rc_id_b)
    check("all 8 twin rc_ids present in source", ids <= set(df.rc_id),
          str(ids - set(df.rc_id)))

    print("hygiene:")
    footer_residue = r"META-(?:START|END)|✍️\s*(?:Musterlösung|Bewertungsmaßstab)\s+erstellt"
    check("no attribution-footer residue in question/GF fields",
          not (df.question_html.str.contains(footer_residue, case=False, regex=True,
                                             na=False).any() or
               df.generalfeedback_html.str.contains(footer_residue, case=False,
                                                     regex=True, na=False).any()))
    check("no textual 'nan'/'None' sentinels in nullable string cols",
          not any(df[c].isin(["nan", "None", ""]).any()
                  for c in ("gf_author_code", "generalfeedback_html", "questionvariables")))

    print("annotations:")
    ap_ = OUT / "data/annotations/all-00000-of-00001.parquet"
    if ap_.exists():
        adf2 = pq.read_table(ap_).to_pandas()
        l2i2 = json.loads((OUT / "vocabulary/label2id.json").read_text(encoding="utf-8"))
        check("2,403 model_generated rows, unique rc_ids",
              len(adf2) == 2403 and adf2.rc_id.nunique() == 2403)
        check("all annotation rc_ids exist in source", adf2.rc_id.isin(df.rc_id).all())
        check("single layer 'model_generated'", (adf2.annotation_layer == "model_generated").all())
        check("annotation policy/version pinned to v1.1",
              (adf2.policy_version == "ANNOTATION_POLICY_v1.1").all()
              and (adf2.vocabulary_version == "v1.1_2026-07").all())
        ok_pairs = all(list(r["concept_ids"]) == [l2i2[lb] for lb in r["concept_labels_de"]]
                       and list(r["concept_ids"]) == sorted(r["concept_ids"])
                       for _, r in adf2.iterrows())
        check("id<->label pairs mapped and canonically ordered", ok_pairs)
        check("statuses within contract",
              set(adf2.annotation_status) <= {"tagged", "tagged_recovered",
                                              "valid_empty", "valid_empty_recovered"})
        check("2,388 tagged + 15 valid-empty rows",
              adf2.annotation_status.value_counts().to_dict()
              == {"tagged": 2388, "valid_empty": 15})
        check("9,148 assignments and 254 concepts used",
              adf2.concept_ids.map(len).sum() == 9148
              and len({cid for values in adf2.concept_ids for cid in values}) == 254)
    else:
        check("annotations table present (build_annotations.py)", False, "missing")

    print("expert reference and leakage-safe splits:")
    expert_path = OUT / "data/expert_reference/all-00000-of-00001.parquet"
    splits_path = OUT / "data/splits/all-00000-of-00001.parquet"
    if expert_path.exists() and splits_path.exists():
        expert = pq.read_table(expert_path).to_pandas()
        splits = pq.read_table(splits_path).to_pandas()
        check("200 single-expert rows", len(expert) == 200 and expert.rc_id.is_unique)
        check("expert samples are 140 probability + 60 diagnostic",
              expert.sample.value_counts().to_dict()
              == {"probability_sample": 140, "diagnostic_sample": 60})
        check("expert rows use v1.1 policy and vocabulary",
              (expert.policy_version == "ANNOTATION_POLICY_v1.1").all()
              and (expert.vocabulary_version == "v1.1_2026-07").all())
        check("2,403 split rows with frozen counts",
              len(splits) == 2403 and splits.rc_id.is_unique
              and splits["split"].value_counts().to_dict()
              == {"train": 1802, "dev": 318, "test_probability": 140,
                  "excluded_near_duplicate": 83, "test_diagnostic": 60})
        train_dev = splits[splits["split"].isin(["train", "dev"])]
        test = splits[splits["split"].isin(
            ["test_probability", "test_diagnostic"])]
        check("zero row/near_duplicate_group overlap with expert test",
              not (set(train_dev.rc_id) & set(test.rc_id))
              and not (set(train_dev.near_duplicate_group_id) & set(test.near_duplicate_group_id)))
    else:
        check("expert_reference and splits tables present", False,
              f"{expert_path.exists()}/{splits_path.exists()}")

    print("solving views:")
    check_solving_views(df)

    print("HF loadability:")
    try:
        from datasets import load_dataset
        d = load_dataset("parquet",
                         data_files=str(OUT / "data/source/all-00000-of-00001.parquet"),
                         split="train")
        check("datasets loads source config", len(d) == 2403)
        ds = load_dataset("parquet",
                          data_files=str(OUT / "data/source/all-00000-of-00001.parquet"),
                          split="train", streaming=True)
        first = next(iter(ds))
        check("streaming mode yields rows", first["rc_id"].startswith("rc-"))
    except Exception as e:
        check("datasets loads source config", False, f"{type(e).__name__}: {e}")

    final_artifacts = {
        "solving_public view": (
            OUT / "data/solving_public/all-00000-of-00001.parquet"
        ),
        "solving_with_keys view": (
            OUT / "data/solving_with_keys/all-00000-of-00001.parquet"
        ),
    }
    print("final checks:")
    if final:
        for name, path in final_artifacts.items():
            check(f"{name} present", path.is_file(), str(path))
    else:
        for name, path in final_artifacts.items():
            state = "ready" if path.is_file() else "pending"
            print(f"  [PENDING] {name}: {state}")

    print()
    if FAILURES:
        sys.exit(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
    if final:
        print("FINAL RELEASE CHECKS PASSED")
    else:
        print("CHECKS PASSED; THE FINAL CHECKS REMAIN")


if __name__ == "__main__":
    args = parse_args()
    try:
        main(final=args.final)
    except SystemExit as exc:
        if exc.code is not None and not isinstance(exc.code, int):
            print(exc.code, file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exc.code if isinstance(exc.code, int) else 1)
    # Exit before interpreter teardown: pyarrow's atexit hooks abort with
    # SIGABRT on some builds, masking a fully successful run.
    sys.stdout.flush()
    os._exit(0)
