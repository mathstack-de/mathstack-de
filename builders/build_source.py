#!/usr/bin/env python3
"""Build the canonical SOURCE table + ASSET tables for the MathStack-DE release.

Builds the source-question table (answer/interaction model, preserve over
interpret) and the asset tables from the canonical corpus XML and the
registers (not included):

  quiz-Math1-Math2.xml, quiz-Numeric.xml   (the cleaned source exports)
  authorship_register.csv          (question and worked-solution authors and
                                    provenance)
  solution_validation_results.csv  (gf_verification_status)

Outputs (out/):
  data/source/all-00000-of-00001.parquet
  assets/assets.parquet, assets/asset_references.parquet
  schema/source.schema.json          (generated from the Arrow schema)
  manifests/source_files.json        (input SHA-256 provenance)

The source and asset tables are derived from the canonical XML and reviewed registers.
Reference labels, splits, and rendered instances are stored in separate tables.

Run: python build_source.py
"""
import base64
import hashlib
import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from author_credits import question_author_credit

HERE = Path(__file__).parent
ROOT = HERE.parent
OUT = HERE / "out"
CORPUS = [ROOT / "not_included/quiz-Math1-Math2.xml", ROOT / "not_included/quiz-Numeric.xml"]

DATASET_VERSION = "1.0.0"
SCHEMA_VERSION = "source_v2"
CD = re.compile(r"<!\[CDATA\[|\]\]>")


# ---------------------------------------------------------------- XML helpers
def inner(block, tag):
    m = re.search(rf"<{tag}[^>]*>\s*<text>(.*?)</text>", block, re.S) or \
        re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    return CD.sub("", m.group(1)).strip() if m else None


def inner_all(block, tag):
    return [CD.sub("", m.group(1)).strip()
            for m in re.finditer(rf"<{tag}[^>]*>\s*<text>(.*?)</text>", block, re.S)]


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


# ------------------------------------------------- per-type answer structures
def parse_answers_generic(block):
    """<answer fraction=..>: shared by multichoice/shortanswer/numerical/truefalse."""
    out = []
    for i, m in enumerate(re.finditer(
            r'<answer[^>]*fraction="([^"]*)"[^>]*>(.*?)</answer>', block, re.S)):
        body = m.group(2)
        text = inner("answer_body_hack", "text")  # placeholder, replaced below
        tm = re.search(r"<text>(.*?)</text>", body, re.S)
        text = CD.sub("", tm.group(1)).strip() if tm else ""
        tol = re.search(r"<tolerance>(.*?)</tolerance>", body, re.S)
        out.append({"option_id": f"a{i+1}", "text": text,
                    "fraction": float(m.group(1) or 0),
                    "tolerance": float(tol.group(1)) if tol and tol.group(1).strip() else None,
                    "group": None, "match_target": None})
    return out


def parse_matching(block):
    out = []
    for i, m in enumerate(re.finditer(r"<subquestion[^>]*>(.*?)</subquestion>", block, re.S)):
        b = m.group(1)
        tm = re.search(r"<text>(.*?)</text>", b, re.S)
        am = re.search(r"<answer>\s*<text>(.*?)</text>", b, re.S)
        out.append({"option_id": f"m{i+1}",
                    "text": CD.sub("", tm.group(1)).strip() if tm else "",
                    "fraction": None, "tolerance": None, "group": None,
                    "match_target": CD.sub("", am.group(1)).strip() if am else None})
    return out


def parse_drag_options(block):
    """ddwtos/gapselect/ddimageortext: dragbox / selectoption / drag elements."""
    out = []
    idx = 0
    for tag in ("dragbox", "selectoption", "drag"):
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.S):
            b = m.group(1)
            idx += 1
            tm = re.search(r"<text>(.*?)</text>", b, re.S)
            gm = re.search(r"<group>(.*?)</group>", b, re.S)
            nm = re.search(r"<no>(.*?)</no>", b, re.S)
            out.append({"option_id": f"d{nm.group(1).strip() if nm else idx}",
                        "text": CD.sub("", tm.group(1)).strip() if tm else "",
                        "fraction": None, "tolerance": None,
                        "group": gm.group(1).strip() if gm else None,
                        "match_target": None})
    return out


def answer_key_json(qtype, block, qt, options):
    """Versioned (answer_key_v1) best-effort machine key. Preserve > interpret;
    None where no auto-gradable key exists (essay/description) or where the
    semantics live in STACK PRTs (stack -> stack_prts_json instead)."""
    key = {"schema": "answer_key_v1", "type": qtype}
    if qtype in ("multichoice", "truefalse", "shortanswer", "numerical", "mtf",
                 "calculated", "calculatedsimple"):
        correct = [o for o in options if (o["fraction"] or 0) > 0]
        if not correct:
            return None
        key["correct_options"] = [
            {"option_id": o["option_id"], "text": o["text"],
             "fraction": o["fraction"], "tolerance": o["tolerance"]} for o in correct]
        return json.dumps(key, ensure_ascii=False)
    if qtype == "matching":
        key["matches"] = [{"option_id": o["option_id"], "text": o["text"],
                           "match_target": o["match_target"]} for o in options]
        return json.dumps(key, ensure_ascii=False)
    if qtype in ("ddwtos", "gapselect"):
        gaps = re.findall(r"\[\[(\d+)\]\]", qt or "")
        key["gap_to_option_no"] = [{"gap_index": i + 1, "option_no": int(g)}
                                   for i, g in enumerate(gaps)]
        return json.dumps(key, ensure_ascii=False) if gaps else None
    if qtype == "ddimageortext":
        drops = [{"drop_no": (re.search(r"<no>(\d+)</no>", m.group(1)) or [None, "?"])[1],
                  "choice": (re.search(r"<choice>(\d+)</choice>", m.group(1)) or [None, None])[1],
                  "xleft": (re.search(r"<xleft>(\d+)</xleft>", m.group(1)) or [None, None])[1],
                  "ytop": (re.search(r"<ytop>(\d+)</ytop>", m.group(1)) or [None, None])[1]}
                 for m in re.finditer(r"<drop>(.*?)</drop>", block, re.S)]
        if not drops:
            return None
        key["drops"] = drops
        return json.dumps(key, ensure_ascii=False)
    if qtype in ("multianswer", "cloze"):  # cloze: subquestions embedded in the text
        subs = re.findall(r"\{#?\d*:(?:NUMERICAL|NM|SHORTANSWER|SA|MC|MULTICHOICE)[^}]*\}",
                          (qt or "") + block)
        if not subs:
            return None
        key["cloze_subquestions_raw"] = subs
        return json.dumps(key, ensure_ascii=False)
    return None


def response_schema_json(qtype, options, stack_inputs):
    s = {"schema": "response_v1", "type": qtype}
    if qtype == "stack":
        s["inputs"] = [{"name": i["input_name"], "input_type": i["input_type"]}
                       for i in (stack_inputs or [])]
    elif qtype in ("multichoice", "mtf"):
        s["response"] = "select_one_or_many"
        s["n_options"] = len(options)
    elif qtype == "truefalse":
        s["response"] = "boolean"
    elif qtype in ("numerical", "calculated", "calculatedsimple"):
        s["response"] = "number"
    elif qtype == "shortanswer":
        s["response"] = "short_text"
    elif qtype == "matching":
        s["response"] = "mapping"
        s["n_pairs"] = len(options)
    elif qtype in ("ddwtos", "gapselect", "ddimageortext"):
        s["response"] = "placement"
        s["n_options"] = len(options)
    elif qtype in ("multianswer", "cloze"):
        s["response"] = "cloze_composite"
    elif qtype == "essay":
        s["response"] = "free_text_ungraded"
    elif qtype == "description":
        s["response"] = "none"
    return json.dumps(s, ensure_ascii=False)


# ------------------------------------------------------------- STACK parsing
STACK_INPUT_TAGS = (
    "name", "type", "tans", "boxsize", "strictsyntax", "insertstars",
    "syntaxhint", "syntaxattribute", "forbidwords", "allowwords",
    "forbidfloat", "requirelowestterms", "checkanswertype", "mustverify",
    "showvalidation", "options",
)
STACK_PRT_TAGS = (
    "name", "value", "autosimplify", "feedbackstyle", "feedbackvariables",
    "node",
)
STACK_NODE_TAGS = (
    "name", "description", "answertest", "sans", "tans", "testoptions",
    "quiet", "truescoremode", "truescore", "truepenalty", "truenextnode",
    "trueanswernote", "truefeedback", "falsescoremode", "falsescore",
    "falsepenalty", "falsenextnode", "falseanswernote", "falsefeedback",
)


def _stack_payload(parent, tag):
    """Return a STACK element's payload without discarding embedded markup."""
    element = parent.find(tag)
    if element is None:
        return ""
    text_element = element.find("text")
    if text_element is not None:
        element = text_element
    payload = element.text or ""
    payload += "".join(ET.tostring(child, encoding="unicode")
                       for child in element)
    return payload.strip()


def _reject_unknown_children(element, allowed, context):
    unknown = sorted({child.tag for child in element} - set(allowed))
    if unknown:
        raise ValueError(f"unrepresented STACK fields in {context}: {unknown}")


def parse_stack(block):
    """Preserve typed inputs and the complete PRT structure used by this corpus.

    The explicit field lists are intentional. A future STACK export that adds a
    field fails the build instead of silently producing a lossy grading record.
    """
    question = ET.fromstring(block)
    rc_id = _stack_payload(question, "idnumber") or "unknown question"

    inputs = []
    for element in question.findall("input"):
        _reject_unknown_children(element, STACK_INPUT_TAGS,
                                 f"input ({rc_id})")
        values = {tag: _stack_payload(element, tag) for tag in STACK_INPUT_TAGS}
        if values["name"]:
            inputs.append({
                "input_name": values["name"],
                "input_type": values["type"],
                "tans_raw": values["tans"],
                "box_size": values["boxsize"],
                "strict_syntax": values["strictsyntax"],
                "insert_stars": values["insertstars"],
                "syntax_hint": values["syntaxhint"],
                "syntax_attribute": values["syntaxattribute"],
                "forbid_words": values["forbidwords"],
                "allow_words": values["allowwords"],
                "forbid_float": values["forbidfloat"],
                "require_lowest_terms": values["requirelowestterms"],
                "check_answer_type": values["checkanswertype"],
                "must_verify": values["mustverify"],
                "show_validation": values["showvalidation"],
                "options": values["options"],
            })

    prts = []
    for element in question.findall("prt"):
        _reject_unknown_children(element, STACK_PRT_TAGS, f"PRT ({rc_id})")
        nodes = []
        for node in element.findall("node"):
            _reject_unknown_children(node, STACK_NODE_TAGS,
                                     f"PRT node ({rc_id})")
            values = {tag: _stack_payload(node, tag)
                      for tag in STACK_NODE_TAGS}
            values["truefeedback_format"] = (
                node.find("truefeedback").get("format", "")
                if node.find("truefeedback") is not None else ""
            )
            values["falsefeedback_format"] = (
                node.find("falsefeedback").get("format", "")
                if node.find("falsefeedback") is not None else ""
            )
            nodes.append(values)
        prts.append({
            "prt_name": _stack_payload(element, "name"),
            "value": _stack_payload(element, "value"),
            "autosimplify": _stack_payload(element, "autosimplify"),
            "feedback_style": _stack_payload(element, "feedbackstyle"),
            "feedback_variables": _stack_payload(element, "feedbackvariables"),
            "nodes": nodes,
        })

    seeds = [int((element.text or "").strip())
             for element in question.findall("deployedseed")
             if (element.text or "").strip()]
    prts_json = json.dumps(
        {"schema": "stack_prts_v2", "prts": prts}, ensure_ascii=False
    ) if prts else None
    return inputs, prts_json, seeds


# ------------------------------------------------------------------ assets
ASSET_FILE = re.compile(
    r'<file([^>]*)name="([^"]*)"([^>]*?)(?:encoding="base64"[^>]*)?>([A-Za-z0-9+/=\s]+?)</file>', re.S)


def scan_assets(block, rc_id, field_hint, assets, refs):
    for m in re.finditer(r'<file[^>]*name="([^"]*)"[^>]*>(.*?)</file>', block, re.S):
        name, payload = m.group(1), m.group(2).strip()
        if not payload or len(payload) < 16:
            continue
        try:
            raw = base64.b64decode(payload, validate=False)
        except Exception:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if sha not in assets:
            mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else \
                   "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else \
                   "image/gif" if raw[:4] == b"GIF8" else \
                   "image/svg+xml" if b"<svg" in raw[:512] else \
                   "application/pdf" if raw[:5] == b"%PDF-" else "application/octet-stream"
            assets[sha] = {"asset_sha256": sha, "mime_type": mime,
                           "byte_size": len(raw),
                           "creator": None, "license": None, "attribution_text": None,
                           "metadata_scan": "pending", "release_decision": "pending"}
        refs.append({"asset_reference_id": f"ref-{len(refs)+1:04d}",
                     "asset_sha256": sha, "rc_id": rc_id,
                     "original_filename": name, "xml_field": field_hint})


# ------------------------------------------------------------------- build
def build_attribution_table():
    """Publish EVERY migrated attribution record (1,576) as its own table.
    The authorship register narrows footers into authorship roles (1,563 rows)
    and is the wrong source for full attribution: 12 grading-rubric credits
    ('Bewertungsmassstab erstellt von ...') and 1 questiontext-field record
    would silently disappear. gf_author_code stays separate."""
    meta = pd.read_csv(ROOT / "not_included/meta_attribution.csv", encoding="utf-8")

    def att_type(row):
        t = row["attribution_text"]
        if "Bewertungsma" in t:
            return "rubric_credit"
        if "Wikipedia" in t:
            return "source_reference"
        author = row.get("author")
        if author is not None and not pd.isna(author) and str(author).strip():
            return "solution_author"
        return "institutional_credit"     # e.g. 'Musterlösung TH Köln' (no named person)

    meta["attribution_type"] = meta.apply(att_type, axis=1)
    tbl = meta[["rc_id", "field", "attribution_text", "author", "attribution_type"]]
    schema = pa.schema([
        ("rc_id", pa.string()),
        ("field", pa.string()),
        ("attribution_text", pa.string()),
        ("author", pa.string()),
        ("attribution_type", pa.string()),
    ])
    (OUT / "data/attribution").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(tbl, schema=schema, preserve_index=False),
                   OUT / "data/attribution/all-00000-of-00001.parquet")
    return len(tbl)


def load_registers():
    reg = pd.read_csv(ROOT / "not_included/authorship_register.csv", encoding="utf-8-sig")
    reg = reg.set_index("rc_id")
    p = ROOT / "not_included/solution_validation_results.csv"
    if not p.exists():
        raise FileNotFoundError(
            "solution validation results missing (not_included/)")
    solution_validation = {}
    for _, r in pd.read_csv(p, encoding="utf-8-sig").iterrows():
        solution_validation[r["rc_id"]] = r["status"]
    return reg, solution_validation, p


def main():
    reg, solution_validation, solution_validation_path = load_registers()
    rows, assets, refs = [], {}, []
    src_manifest = {}

    for f in CORPUS:
        s = f.read_text(encoding="utf-8")
        src_manifest[f.name] = hashlib.sha256(s.encode("utf-8")).hexdigest()
        source_bank_category = "?"
        for m in re.finditer(r'<question type="(\w+)">.*?</question>', s, re.S):
            qtype, block = m.group(1), m.group(0)
            if qtype == "category":
                path = inner(block, "category") or "?"
                source_bank_category = path.replace("$course$/top/", "")
                continue
            rc = (re.search(r"<idnumber>(rc-[0-9a-f-]{36})</idnumber>", block) or [None, None])[1]
            name = inner(block, "name") or ""
            qt = inner(block, "questiontext")
            gf = inner(block, "generalfeedback") or None
            qv = (inner(block, "questionvariables") or None) if qtype == "stack" else None

            if qtype == "matching":
                options = parse_matching(block)
            elif qtype in ("ddwtos", "gapselect", "ddimageortext"):
                options = parse_drag_options(block)
            elif qtype != "stack":
                options = parse_answers_generic(block)
            else:
                options = []

            stack_inputs, prts_json, seeds = parse_stack(block) if qtype == "stack" else (None, None, [])

            scan_assets(block, rc, "question_block", assets, refs)

            a = reg.loc[rc] if rc in reg.index else None
            # a worked solution must have substantive content: visible text or
            # an embedded image. Four STACK GFs held only an attribution footer
            # pre-migration and are empty markup now -> no solution.
            has_gf = bool(gf) and bool(strip_html(gf) or "<img" in gf.lower()
                                       or "pluginfile" in gf.lower())
            question_author_code = (
                None
                if a is None or pd.isna(a.get("question_author"))
                else str(a["question_author"])
            )
            registered_gf_provenance = (
                None
                if a is None or pd.isna(a.get("gf_provenance"))
                or not str(a.get("gf_provenance")).strip()
                else str(a["gf_provenance"])
            )
            registered_gf_verification = (
                None
                if a is None or pd.isna(a.get("gf_verification_status"))
                or not str(a.get("gf_verification_status")).strip()
                else str(a["gf_verification_status"])
            )
            registered_gf_attribution = (
                None
                if a is None or pd.isna(a.get("gf_attribution_text"))
                or not str(a.get("gf_attribution_text")).strip()
                else str(a["gf_attribution_text"])
            )
            rows.append({
                "dataset_version": DATASET_VERSION,
                "schema_version": SCHEMA_VERSION,
                "rc_id": rc,
                "content_sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "source_xml_file": f.name,
                "name": name,
                "question_type": qtype,
                "topic_path": source_bank_category,
                "question_author_code": question_author_code,
                "question_author_credit": (
                    None
                    if question_author_code is None
                    else question_author_credit(question_author_code)
                ),
                "gf_author_code": (None if a is None or not has_gf or pd.isna(a.get("gf_author_code"))
                                   or not str(a.get("gf_author_code")).strip()
                                   else str(a["gf_author_code"])),
                "gf_attribution_text": (
                    registered_gf_attribution if has_gf else None
                ),
                "question_html": qt,
                "question_text_template": strip_html(qt),
                "answer_options": options or None,
                "generalfeedback_html": gf,
                "gf_provenance": (
                    registered_gf_provenance
                    if has_gf and registered_gf_provenance
                    else "human" if has_gf else "none"
                ),
                "gf_verification_status": (
                    registered_gf_verification
                    if has_gf and registered_gf_verification
                    else solution_validation.get(rc) if has_gf else None
                ),
                "questionvariables": qv,
                "response_schema_json": response_schema_json(qtype, options, stack_inputs),
                "answer_key_json": answer_key_json(qtype, block, qt, options),
                "stack_inputs": stack_inputs,
                "stack_prts_json": prts_json,
                "deployed_seeds": seeds,
                "content_license": "CC-BY-SA-4.0",
                "has_generalfeedback": has_gf,
                # one STACK record is a free-text notes question without any
                # grading tree; solving views must exclude non-gradable rows
                "is_auto_gradable": (
                    prts_json is not None if qtype == "stack"
                    else qtype in ("multichoice", "truefalse", "numerical",
                                   "shortanswer", "matching", "ddwtos",
                                   "gapselect", "ddimageortext", "cloze",
                                   "multianswer", "mtf")),
            })

    df = pd.DataFrame(rows)

    # ---- explicit Arrow schema (explicit features, real nulls)
    opt_struct = pa.struct([("option_id", pa.string()), ("text", pa.string()),
                            ("fraction", pa.float64()), ("tolerance", pa.float64()),
                            ("group", pa.string()), ("match_target", pa.string())])
    inp_struct = pa.struct([
        ("input_name", pa.string()), ("input_type", pa.string()),
        ("tans_raw", pa.string()), ("box_size", pa.string()),
        ("strict_syntax", pa.string()), ("insert_stars", pa.string()),
        ("syntax_hint", pa.string()), ("syntax_attribute", pa.string()),
        ("forbid_words", pa.string()), ("allow_words", pa.string()),
        ("forbid_float", pa.string()), ("require_lowest_terms", pa.string()),
        ("check_answer_type", pa.string()), ("must_verify", pa.string()),
        ("show_validation", pa.string()), ("options", pa.string()),
    ])
    schema = pa.schema([
        ("dataset_version", pa.string()), ("schema_version", pa.string()),
        ("rc_id", pa.string()), ("content_sha256", pa.string()),
        ("source_xml_file", pa.string()), ("name", pa.string()),
        ("question_type", pa.string()), ("topic_path", pa.string()),
        ("question_author_code", pa.string()),
        ("question_author_credit", pa.string()),
        ("gf_author_code", pa.string()),
        ("gf_attribution_text", pa.string()),
        ("question_html", pa.string()), ("question_text_template", pa.string()),
        ("answer_options", pa.list_(opt_struct)),
        ("generalfeedback_html", pa.string()), ("gf_provenance", pa.string()),
        ("gf_verification_status", pa.string()), ("questionvariables", pa.string()),
        ("response_schema_json", pa.string()), ("answer_key_json", pa.string()),
        ("stack_inputs", pa.list_(inp_struct)), ("stack_prts_json", pa.string()),
        ("deployed_seeds", pa.list_(pa.int64())),
        ("content_license", pa.string()), ("has_generalfeedback", pa.bool_()),
        ("is_auto_gradable", pa.bool_()),
    ])
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)

    (OUT / "data/source").mkdir(parents=True, exist_ok=True)
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    (OUT / "schema").mkdir(parents=True, exist_ok=True)
    (OUT / "manifests").mkdir(parents=True, exist_ok=True)

    pq.write_table(table, OUT / "data/source/all-00000-of-00001.parquet",
                   row_group_size=512)

    adf = pd.DataFrame(list(assets.values()))
    rdf = pd.DataFrame(refs)
    if len(adf):
        pq.write_table(pa.Table.from_pandas(adf, preserve_index=False),
                       OUT / "assets/assets.parquet")
        pq.write_table(pa.Table.from_pandas(rdf, preserve_index=False),
                       OUT / "assets/asset_references.parquet")

    # generated JSON schema (field -> arrow type string)
    (OUT / "schema/source.schema.json").write_text(json.dumps(
        {"schema_version": SCHEMA_VERSION,
         "fields": {f.name: str(f.type) for f in schema}}, indent=2), encoding="utf-8")
    (OUT / "schema/schema_version.txt").write_text(SCHEMA_VERSION + "\n")

    n_att = build_attribution_table()

    git = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "-uno"],
                                capture_output=True, text=True).stdout.strip())
    # Hash every consumed input plus the builder itself. Record paths as well as
    # digests so the release validator can reject stale generated tables.
    manifest_paths = {f.name: f for f in CORPUS}
    manifest_paths.update({
        "authorship_register": ROOT / "not_included/authorship_register.csv",
        "meta_attribution": ROOT / "not_included/meta_attribution.csv",
        "solution_validation_results": solution_validation_path,
        "builder_code": Path(__file__),
    })
    for tag, path in manifest_paths.items():
        if path.exists():
            src_manifest[tag] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "manifests/source_files.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mathstack_commit": git, "mathstack_dirty": dirty,
        "dataset_version": DATASET_VERSION,
        "input_paths": {
            tag: str(path.resolve().relative_to(ROOT.resolve()))
            for tag, path in manifest_paths.items()
        },
        "inputs_sha256": src_manifest,
        "rows": len(df), "assets": len(adf), "asset_references": len(rdf),
        "attribution_records": n_att,
    }, indent=2), encoding="utf-8")

    print(f"source rows: {len(df)}  (stack {sum(df.question_type=='stack')}, "
          f"with GF {int(df.has_generalfeedback.sum())})")
    print(f"assets: {len(adf)} unique payloads, {len(rdf)} references")
    print(f"attribution table: {n_att} records (full migration register)")
    print(f"gf_verification_status coverage: {df.gf_verification_status.notna().sum()}")
    print("->", OUT / "data/source/all-00000-of-00001.parquet")


if __name__ == "__main__":
    main()
