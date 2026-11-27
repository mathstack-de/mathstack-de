"""pytest over the built release artifacts (run the builders first)."""
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
import pytest

OUT = Path(__file__).parent / "out"

pytestmark = pytest.mark.skipif(
    not (OUT / "data/source/all-00000-of-00001.parquet").exists(),
    reason="run build_source.py first")


@pytest.fixture(scope="module")
def source():
    return pq.read_table(OUT / "data/source/all-00000-of-00001.parquet").to_pandas()


def test_counts(source):
    assert len(source) == 2403
    assert (source.question_type == "stack").sum() == 1604
    # 1,574: four STACK GFs were attribution-footer-only (no solution content)
    assert ((source.gf_provenance == "human") & source.has_generalfeedback).sum() == 1574
    ai = source[source.gf_provenance.str.startswith("ai_generated", na=False)]
    assert len(ai) == 111
    assert set(ai.gf_author_code) == {"AI"}
    assert source.has_generalfeedback.sum() == 1685
    assert source.gf_verification_status.notna().sum() == 1395


def test_generated_worked_solution_release_tiers(source):
    path = (
        OUT
        / "data/generated_worked_solutions/all-00000-of-00001.parquet"
    )
    manifest_path = OUT / "manifests/generated_worked_solutions_manifest.json"
    assert path.exists() and manifest_path.exists()

    generated = pq.read_table(path).to_pandas()
    assert len(generated) == 252 and generated.rc_id.is_unique
    assert generated.release_tier.value_counts().to_dict() == {
        "machine_checked_not_expert_reviewed": 141,
        "expert_approved": 111,
    }
    assert set(generated.gf_author_code) == {"AI"}
    assert set(generated.content_license) == {"CC-BY-SA-4.0"}
    assert generated.generation_candidate_full_credit.all()
    assert generated.annotation_context_used.all()
    assert set(generated.rc_id) <= set(source.rc_id)

    expert = generated[generated.release_tier == "expert_approved"]
    machine = generated[
        generated.release_tier == "machine_checked_not_expert_reviewed"
    ]
    assert set(expert.rc_id) == set(
        source[source.gf_provenance.str.startswith("ai_generated", na=False)].rc_id
    )
    assert machine.generation_candidate_presentation_clean.all()
    assert machine.generation_candidate_result_match.all()
    assert (machine.generation_links_flagged == 0).all()
    assert not set(machine.rc_id) & set(source[source.has_generalfeedback].rc_id)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows"] == 252
    assert manifest["annotation_context_full_credit_total"] == 255
    assert len(manifest["excluded_full_credit_rows"]) == 3


def test_rc_ids_unique_and_valid(source):
    assert source.rc_id.nunique() == 2403
    assert source.rc_id.str.match(r"rc-[0-9a-f-]{36}$").all()


def test_multi_input_stack_preserved(source):
    stack = source[source.question_type == "stack"]
    n = stack.stack_inputs.map(lambda x: len(x) if x is not None else 0)
    assert (n > 1).sum() == 582
    assert n.max() == 24


def test_stack_contract_v2_preserves_all_exported_fields(source):
    stack = source[source.question_type == "stack"]
    assert set(stack.schema_version) == {"source_v2"}

    input_fields = {
        "input_name", "input_type", "tans_raw", "box_size",
        "strict_syntax", "insert_stars", "syntax_hint",
        "syntax_attribute", "forbid_words", "allow_words", "forbid_float",
        "require_lowest_terms", "check_answer_type", "must_verify",
        "show_validation", "options",
    }
    assert all(input_fields == set(item)
               for inputs in stack.stack_inputs for item in inputs)

    prt_fields = {
        "prt_name", "value", "autosimplify", "feedback_style",
        "feedback_variables", "nodes",
    }
    node_fields = {
        "name", "description", "answertest", "sans", "tans",
        "testoptions", "quiet", "truescoremode", "truescore",
        "truepenalty", "truenextnode", "trueanswernote", "truefeedback",
        "falsescoremode", "falsescore", "falsepenalty", "falsenextnode",
        "falseanswernote", "falsefeedback", "truefeedback_format",
        "falsefeedback_format",
    }
    prt_count = node_count = 0
    for raw in stack.stack_prts_json.dropna():
        contract = json.loads(raw)
        assert contract["schema"] == "stack_prts_v2"
        for prt in contract["prts"]:
            assert set(prt) == prt_fields
            prt_count += 1
            for node in prt["nodes"]:
                assert set(node) == node_fields
                node_count += 1
    assert prt_count == 2690
    assert node_count == 3469


def test_stack_contract_parser_rejects_unrepresented_fields():
    from build_source import parse_stack

    block = """
    <question type="stack">
      <idnumber>rc-00000000-0000-0000-0000-000000000000</idnumber>
      <input><name>ans1</name><type>algebraic</type><tans>x</tans>
        <futureconstraint>1</futureconstraint></input>
    </question>
    """
    with pytest.raises(ValueError, match="unrepresented STACK fields"):
        parse_stack(block)


def test_seeds_int64_roundtrip(source):
    import pyarrow as pa
    t = pq.read_table(OUT / "data/source/all-00000-of-00001.parquet")
    ft = t.schema.field("deployed_seeds").type
    assert pa.types.is_list(ft) and pa.types.is_int64(ft.value_type)
    mx = max((max(s) for s in source.deployed_seeds if len(s)), default=0)
    assert mx == 8898666092


def test_assets():
    a = pq.read_table(OUT / "assets/assets.parquet").to_pandas()
    r = pq.read_table(OUT / "assets/asset_references.parquet").to_pandas()
    assert len(a) == 184 and len(r) == 233
    assert r.asset_sha256.isin(a.asset_sha256).all()


def test_vocabulary():
    l2i = json.loads((OUT / "vocabulary/label2id.json").read_text(encoding="utf-8"))
    order = json.loads((OUT / "vocabulary/labels_order.json").read_text(encoding="utf-8"))
    assert len(l2i) == 271
    assert order["vocabulary_version"] == "v1.1_2026-07"
    assert order["order"] == sorted(set(l2i.values()))
    public = yaml.safe_load(
        (OUT / "vocabulary/concept_vocabulary.v1_1.yaml").read_text(
            encoding="utf-8"))
    entries = [entry for group in public.values() for entry in group]
    fields = {key for entry in entries for key in entry}
    assert len(entries) == 271
    assert {"id", "de", "en", "type"} <= fields
    assert not fields & {"note", "proposed"}


def test_expert_reference_manifest():
    g = pd.read_csv(OUT / "manifests/expert_reference_manifest.csv")
    rt = g[g.sample == "probability_sample"]
    assert (len(rt), len(g) - len(rt)) == (140, 60)
    assert abs(rt.design_weight.sum() - 1574) < 1e-6


def test_no_meta_footers(source):
    assert not source.question_html.str.contains("META-START", na=False).any()
    assert not source.generalfeedback_html.str.contains("META-START", na=False).any()


# ---------------- negative tests ------------------------------------------------

def _run_build_annotations(tmp_path, mutate):
    """Copy canonical CSV+manifest, apply `mutate`, run the builder, return rc."""
    import shutil
    import subprocess
    import sys
    current = (
        Path(__file__).parent.parent / "not_included/model_generated_labels_v1_1"
    )
    src = current / "model_generated_labels_v1_1.csv"
    man = current / "model_generated_labels_v1_1.manifest.json"
    assert src.exists() and man.exists(), \
        "canonical v1.1 model_generated CSV/manifest absent"
    csv_c = tmp_path / "n.csv"
    man_c = tmp_path / "n.manifest.json"
    shutil.copy2(src, csv_c)
    shutil.copy2(man, man_c)
    mutate(csv_c, man_c)
    r = subprocess.run([sys.executable, str(Path(__file__).parent / "build_annotations.py"),
                        str(csv_c), str(man_c)], capture_output=True, text=True)
    return r


def test_tampered_csv_rejected(tmp_path):
    def mutate(csv_c, man_c):
        csv_c.write_text(csv_c.read_text(encoding="utf-8-sig").replace(
            "Graph", "Graf", 1), encoding="utf-8-sig")
    r = _run_build_annotations(tmp_path, mutate)
    assert r.returncode != 0 and "manifest output hash" in (r.stdout + r.stderr)


def test_permuted_labels_rejected(tmp_path):
    import hashlib, json
    def mutate(csv_c, man_c):
        lines = csv_c.read_text(encoding="utf-8-sig").splitlines()
        for i, ln in enumerate(lines):
            if "|" in ln.split(",")[1] if len(ln.split(",")) > 1 else False:
                pass
        # swap the order of the first multi-label row's labels (ids stay)
        import csv as _csv, io
        rows = list(_csv.DictReader(io.StringIO("\n".join(lines))))
        for row in rows:
            labs = row["concept_labels"].split("|")
            if len(labs) >= 2:
                row["concept_labels"] = "|".join([labs[1], labs[0]] + labs[2:])
                break
        buf = io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
        csv_c.write_text(buf.getvalue(), encoding="utf-8-sig")
        # re-record the hash so authentication passes and the MAPPING check fires
        m = json.loads(man_c.read_text())
        m["sha256"]["output"] = hashlib.sha256(csv_c.read_bytes()).hexdigest()
        man_c.write_text(json.dumps(m))
    r = _run_build_annotations(tmp_path, mutate)
    assert r.returncode != 0 and "pair mismatch" in (r.stdout + r.stderr)


def test_duplicate_rc_id_rejected(tmp_path):
    import hashlib, json
    def mutate(csv_c, man_c):
        lines = csv_c.read_text(encoding="utf-8-sig").splitlines()
        lines.append(lines[1])          # duplicate first data row
        csv_c.write_text("\n".join(lines), encoding="utf-8-sig")
        m = json.loads(man_c.read_text())
        m["sha256"]["output"] = hashlib.sha256(csv_c.read_bytes()).hexdigest()
        man_c.write_text(json.dumps(m))
    r = _run_build_annotations(tmp_path, mutate)
    assert r.returncode != 0 and "unique rc_ids" in (r.stdout + r.stderr)


def test_attribution_table_complete():
    table = pq.read_table(OUT / "data/attribution/all-00000-of-00001.parquet")
    assert all(pa.types.is_string(field.type) for field in table.schema)
    t = table.to_pandas()
    assert len(t) == 1576
    assert (t.attribution_type == "solution_author").sum() == 1349
    assert (t.attribution_type == "institutional_credit").sum() == 213
    assert (t.attribution_type == "rubric_credit").sum() == 12
    assert (t.attribution_type == "source_reference").sum() == 2
    assert (t.field == "questiontext").sum() == 1


def test_question_author_credit_travels_with_source_rows():
    source = pq.read_table(
        OUT / "data/source/all-00000-of-00001.parquet"
    ).to_pandas()
    assert source.question_author_credit.notna().all()
    az = source[source.question_author_code == "A3"]
    assert len(az) == 860
    assert az.question_author_credit.nunique() == 1
    credit = az.question_author_credit.iloc[0]
    assert credit == (
        "CIH HTW Berlin and Karlsruhe University of Applied Sciences (joint source bank)")
    project = source[source.question_author_code == "A0"]
    assert len(project) == 1
    assert project.iloc[0].rc_id == \
        "rc-70e21739-b124-4f9f-bce7-e20dc49a952d"
    assert project.iloc[0].question_author_credit == \
        "MathStack-DE project (independently authored replacement)"


def test_expert_reference_and_splits():
    expert = pq.read_table(
        OUT / "data/expert_reference/all-00000-of-00001.parquet"
    ).to_pandas()
    splits = pq.read_table(OUT / "data/splits/all-00000-of-00001.parquet").to_pandas()
    assert len(expert) == 200 and expert.rc_id.is_unique
    assert expert.sample.value_counts().to_dict() == {
        "probability_sample": 140, "diagnostic_sample": 60}
    assert len(splits) == 2403 and splits.rc_id.is_unique
    assert splits["split"].value_counts().to_dict() == {
        "train": 1802, "dev": 318, "test_probability": 140,
        "excluded_near_duplicate": 83, "test_diagnostic": 60}
    train_dev = splits[splits["split"].isin(["train", "dev"])]
    test = splits[splits["split"].isin(["test_probability", "test_diagnostic"])]
    assert not (set(train_dev.near_duplicate_group_id) & set(test.near_duplicate_group_id))


def test_annotation_rows_cover_definition_bank_questions():
    annotations = pq.read_table(
        OUT / "data/annotations/all-00000-of-00001.parquet"
    ).to_pandas()
    source = pq.read_table(
        OUT / "data/source/all-00000-of-00001.parquet",
        columns=["rc_id", "topic_path"],
    ).to_pandas()
    topics = dict(zip(source.rc_id, source.topic_path))
    broad = annotations[
        annotations.rc_id.map(topics).str.startswith("DEFINITIONS ")
        & annotations.concept_ids.map(len).gt(0)
    ]
    assert len(broad) > 0


def test_annotation_manifest_has_no_absolute_host_paths():
    manifest = json.loads(
        (OUT / "manifests/annotation_run_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    def strings(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from strings(child)
        elif isinstance(value, list):
            for child in value:
                yield from strings(child)
        elif isinstance(value, str):
            yield value

    assert not [value for value in strings(manifest) if Path(value).is_absolute()]


def test_hf_source_split_is_not_reserved_all():
    # The card of the dataset release (its README.md).
    card = (Path(__file__).parent.parent / "not_included/dataset/README.md"
            ).read_text(encoding="utf-8")
    front_matter = yaml.safe_load(card.split("---", 2)[1])
    source = next(c for c in front_matter["configs"] if c["config_name"] == "source")
    assert source["data_files"] == [
        {"split": "full", "path": "data/source/all-*.parquet"}
    ]


def test_is_auto_gradable(source):
    assert "is_auto_gradable" in source.columns
    stack_ng = source[(source.question_type == "stack") & ~source.is_auto_gradable]
    assert len(stack_ng) == 1          # the free-text notes question
    assert (~source.is_auto_gradable).sum() == 156   # + essay 94 + description 61


def test_expert_reference_manifest_freeze_metadata():
    import json
    m = json.loads((OUT / "manifests/expert_reference_manifest.json").read_text(encoding="utf-8"))
    assert m["draw_version"] == 2 and m["seed"] == 20260710
    assert m["sampling_unit"] == "rc_id"
    assert set(m["sha256"]) >= {"sampler_code", "quarantine_csv", "quarantine_xml"}


def test_solving_views_paired_and_leak_free():
    import json
    import pytest
    pub_path = OUT / "data/solving_public/all-00000-of-00001.parquet"
    keys_path = OUT / "data/solving_with_keys/all-00000-of-00001.parquet"
    if not (pub_path.exists() and keys_path.exists()):
        pytest.skip("solving views not built yet (build_solving.py)")
    pub = pq.read_table(pub_path).to_pandas()
    keys = pq.read_table(keys_path).to_pandas()
    src = pq.read_table(
        OUT / "data/source/all-00000-of-00001.parquet").to_pandas()
    gradable = src[(src.question_type == "stack") & src.is_auto_gradable]
    assert len(pub) == len(gradable)
    assert set(pub.rc_id) == set(gradable.rc_id)
    assert pub.variant_id.is_unique
    assert set(pub.variant_id) == set(keys.variant_id)
    assert set(pub.schema_version) == {"solving_v2"}
    assert set(keys.schema_version) == {"solving_v2"}
    forbidden = {"expected_responses", "generalfeedback_rendered",
                 "questionvariables", "stack_prts_json", "questionnote"}
    assert not (forbidden & set(pub.columns))
    assert "questionnote" not in keys.columns
    merged = pub.merge(keys, on="variant_id", suffixes=("_p", "_k"))
    assert (merged.question_text_rendered_p
            == merged.question_text_rendered_k).all()
    assert (merged.render_sha256_p == merged.render_sha256_k).all()
    assert keys.expected_responses.map(
        lambda v: isinstance(v, str) and v not in ("", "{}")).all()
    source_prts = gradable.set_index("rc_id").stack_prts_json
    key_prts = keys.set_index("rc_id").stack_prts_json
    assert key_prts.equals(source_prts.loc[key_prts.index])
    assert keys.stack_prts_json.map(
        lambda raw: json.loads(raw)["schema"] == "stack_prts_v2").all()
    leaked = merged.apply(
        lambda r: any(len(str(v)) >= 8 and str(v) in r.question_text_rendered_p
                      for v in json.loads(r.expected_responses).values()),
        axis=1)
    assert not leaked.any()
