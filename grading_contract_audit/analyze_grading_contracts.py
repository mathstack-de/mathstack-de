#!/usr/bin/env python3
"""Audit STACK grading-contract structure in the canonical corpus.

The primary comparison is deliberately narrow and structural. A question has
``direct_equivalence_only`` PRT logic only when every answer input maps
one-to-one to a single terminal node that performs a default, binary
``AlgEquiv`` comparison. Input parsing constraints and authored feedback are
reported separately; they do not inflate the primary count.

Outputs are deterministic and contain no rendered answers or student data:

  question_features.csv
  summary.json
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
CORPUS_FILES = (
    ROOT / "not_included/quiz-Math1-Math2.xml",
    ROOT / "not_included/quiz-Numeric.xml",
)
# The source exports as they stood when the study questions were generated
# (not included).
STUDY_CORPUS_SNAPSHOT = ROOT / "not_included/study_corpus_snapshot"
# The draw of the study (variant_study/draw.py writes it; not included).
STUDY_SELECTION = ROOT / "not_included/variant_study_selection.csv"
STUDY_RESULTS = ROOT / "variant_study/results.csv"
STUDY_PAPER_SCOPE = ROOT / "variant_study/paper_scope_summary.json"
OUT_DIR = ROOT / "grading_contract_audit"
OUT_CSV = OUT_DIR / "question_features.csv"
OUT_JSON = OUT_DIR / "summary.json"

EXPECTED_STACK_QUESTIONS = 1_604
EXPECTED_PRTLESS_QUESTIONS = 1


def clean(value: str | None) -> str:
    return (value or "").strip()


def as_float(value: str | None) -> float | None:
    value = clean(value)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_fragments(xml_bytes: bytes) -> dict[str, bytes]:
    root = ET.fromstring(xml_bytes)
    fragments = {}
    for question in root.findall("question"):
        if question.get("type") != "stack":
            continue
        rc_id = clean(question.findtext("idnumber"))
        fragments[rc_id] = b"".join(
            ET.tostring(node) for node in [*question.findall("input"), *question.findall("prt")]
        )
    return fragments


def selected_contract_digest(fragments: dict[str, bytes], ids: set[str]) -> str:
    digest = hashlib.sha256()
    for rc_id in sorted(ids):
        if rc_id not in fragments:
            raise SystemExit(f"selected question missing from contract snapshot: {rc_id}")
        digest.update(rc_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(fragments[rc_id])
        digest.update(b"\0")
    return digest.hexdigest()


def is_terminal(node: ET.Element, branch: str) -> bool:
    return clean(node.findtext(f"{branch}nextnode")) in {"", "-1"}


def branch_is_basic(node: ET.Element, branch: str, expected: float) -> bool:
    score = as_float(node.findtext(f"{branch}score"))
    mode = clean(node.findtext(f"{branch}scoremode"))
    # A terminal one-node PRT starts at zero. Setting the true branch to one
    # and adding one are therefore equivalent; adding or subtracting zero on
    # the false branch is likewise equivalent to setting zero. Treat those XML
    # encodings as the same binary contract rather than inflating complexity.
    mode_is_basic = (
        mode in {"=", "+"} if expected == 1.0 else mode in {"=", "+", "-"}
    )
    return (
        mode_is_basic
        and score == expected
        and is_terminal(node, branch)
    )


def input_inventory(inputs: list[ET.Element]) -> dict[str, bool]:
    answer_inputs = [node for node in inputs if clean(node.findtext("type")) != "notes"]
    types = [clean(node.findtext("type")) for node in answer_inputs]

    explicit_format_restriction = any(
        clean(node.findtext("requirelowestterms")) == "1"
        or clean(node.findtext("checkanswertype")) == "1"
        or bool(clean(node.findtext("forbidwords")))
        or bool(clean(node.findtext("options")))
        for node in answer_inputs
    )
    return {
        "has_non_algebraic_input": any(value != "algebraic" for value in types),
        "has_explicit_format_restriction": explicit_format_restriction,
        # Reported separately because it is nearly corpus-wide and may reflect
        # an authoring default rather than a question-specific design choice.
        "forbids_decimal_float": any(
            clean(node.findtext("forbidfloat")) == "1" for node in answer_inputs
        ),
    }


def analyze_question(question: ET.Element, source_file: Path) -> dict[str, object]:
    rc_id = clean(question.findtext("idnumber"))
    name = clean(question.findtext("name/text"))
    inputs = question.findall("input")
    answer_inputs = [node for node in inputs if clean(node.findtext("type")) != "notes"]
    answer_input_names = [clean(node.findtext("name")) for node in answer_inputs]
    prts = question.findall("prt")
    nodes = [node for prt in prts for node in prt.findall("node")]

    answer_tests = [clean(node.findtext("answertest")) for node in nodes]
    student_expressions = [clean(node.findtext("sans")) for node in nodes]
    target_expressions = [clean(node.findtext("tans")) for node in nodes]

    has_non_alg_equiv_test = any(value != "AlgEquiv" for value in answer_tests)
    has_multi_node_prt = any(len(prt.findall("node")) != 1 for prt in prts)
    has_branching = any(
        not is_terminal(node, branch)
        for node in nodes
        for branch in ("true", "false")
    )
    has_test_options = any(clean(node.findtext("testoptions")) for node in nodes)
    has_derived_student_expression = any(
        value not in answer_input_names for value in student_expressions
    )
    has_nondefault_autosimplify = any(
        clean(prt.findtext("autosimplify")) not in {"", "1"} for prt in prts
    )

    scores = [
        as_float(node.findtext(f"{branch}score"))
        for node in nodes
        for branch in ("true", "false")
    ]
    has_partial_credit_score = any(
        score is not None and 0.0 < score < 1.0 for score in scores
    )
    has_nonbinary_score_logic = any(
        not branch_is_basic(node, "true", 1.0)
        or not branch_is_basic(node, "false", 0.0)
        for node in nodes
    )

    full_credit_targets: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        if branch_is_basic(node, "true", 1.0):
            full_credit_targets[clean(node.findtext("sans"))].add(
                clean(node.findtext("tans"))
            )
    has_multiple_full_credit_targets = any(
        len(targets - {""}) > 1 for targets in full_credit_targets.values()
    )

    has_authored_feedback = any(
        clean(node.findtext(path))
        for node in nodes
        for path in ("truefeedback/text", "falsefeedback/text")
    )
    has_feedback_variables = any(
        clean(prt.findtext("feedbackvariables/text")) for prt in prts
    )

    one_to_one_inputs = (
        len(nodes) == len(answer_input_names)
        and Counter(student_expressions) == Counter(answer_input_names)
    )
    direct_equivalence_only = bool(prts) and all(
        (
            len(prt.findall("node")) == 1
            and clean(prt.findtext("autosimplify")) in {"", "1"}
            and clean(prt.findtext("node/answertest")) == "AlgEquiv"
            and not clean(prt.findtext("node/testoptions"))
            and branch_is_basic(prt.find("node"), "true", 1.0)
            and branch_is_basic(prt.find("node"), "false", 0.0)
        )
        for prt in prts
    ) and one_to_one_inputs

    inputs_summary = input_inventory(inputs)
    return {
        "rc_id": rc_id,
        "name": name,
        "source_file": source_file.name,
        "input_count": len(answer_inputs),
        "input_types": ";".join(sorted(set(
            clean(node.findtext("type")) for node in answer_inputs
        ))),
        "prt_count": len(prts),
        "node_count": len(nodes),
        "answer_tests": ";".join(sorted(set(answer_tests))),
        "answer_test_node_counts_json": json.dumps(
            dict(sorted(Counter(answer_tests).items())),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "direct_equivalence_only": direct_equivalence_only,
        "prt_logic_beyond_direct_equivalence": bool(prts) and not direct_equivalence_only,
        "has_non_alg_equiv_test": has_non_alg_equiv_test,
        "has_multi_node_prt": has_multi_node_prt,
        "has_branching": has_branching,
        "has_partial_credit_score": has_partial_credit_score,
        "has_nonbinary_score_logic": has_nonbinary_score_logic,
        "has_test_options": has_test_options,
        "has_derived_student_expression": has_derived_student_expression,
        "has_nondefault_autosimplify": has_nondefault_autosimplify,
        "has_multiple_full_credit_targets": has_multiple_full_credit_targets,
        "has_authored_feedback": has_authored_feedback,
        "has_feedback_variables": has_feedback_variables,
        **inputs_summary,
        "target_expression_count": len(set(target_expressions) - {""}),
    }


def percentage(count: int, denominator: int) -> float:
    return round(100.0 * count / denominator, 1) if denominator else 0.0


def feature_summary(rows: list[dict[str, object]], denominator: int) -> dict[str, dict[str, float | int]]:
    fields = (
        "direct_equivalence_only",
        "prt_logic_beyond_direct_equivalence",
        "has_non_alg_equiv_test",
        "has_multi_node_prt",
        "has_branching",
        "has_partial_credit_score",
        "has_nonbinary_score_logic",
        "has_test_options",
        "has_derived_student_expression",
        "has_nondefault_autosimplify",
        "has_multiple_full_credit_targets",
        "has_non_algebraic_input",
        "has_explicit_format_restriction",
        "forbids_decimal_float",
        "has_authored_feedback",
        "has_feedback_variables",
    )
    return {
        field: {
            "n": (count := sum(bool(row[field]) for row in rows)),
            "percent": percentage(count, denominator),
        }
        for field in fields
    }


def checker_summary(
    result_rows: list[dict[str, str]],
    feature_rows: dict[str, dict[str, object]],
) -> dict[str, object]:
    decisive = [
        row for row in result_rows if row["status"] in {"correct", "wrong", "partial"}
    ]
    output: dict[str, object] = {"decisive_stack_outcomes": len(decisive), "methods": {}}
    for field in ("string_eq", "sympy_eq", "math_verify_eq"):
        covered = [row for row in decisive if row[field] in {"0", "1"}]
        agreements = [
            row
            for row in covered
            if ((row["status"] == "correct") == (row[field] == "1"))
        ]
        disagreements = [row for row in covered if row not in agreements]
        false_rejects = [
            row for row in disagreements if row["status"] == "correct" and row[field] == "0"
        ]
        false_accepts = [
            row for row in disagreements if row["status"] != "correct" and row[field] == "1"
        ]

        by_contract = {}
        for label, feature in (
            ("direct_equivalence_only", "direct_equivalence_only"),
            ("richer_prt_logic", "prt_logic_beyond_direct_equivalence"),
        ):
            subset = [
                row for row in decisive if bool(feature_rows[row["rc_id"]][feature])
            ]
            subset_covered = [row for row in subset if row[field] in {"0", "1"}]
            subset_agreements = [
                row
                for row in subset_covered
                if ((row["status"] == "correct") == (row[field] == "1"))
            ]
            subset_disagreements = [
                row for row in subset_covered if row not in subset_agreements
            ]
            by_contract[label] = {
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

        output["methods"][field] = {  # type: ignore[index]
            "coverage_n": len(covered),
            "coverage_percent": percentage(len(covered), len(decisive)),
            "no_verdict_n": len(decisive) - len(covered),
            "agreement_n": len(agreements),
            "conditional_agreement_percent": percentage(len(agreements), len(covered)),
            "false_reject_n": len(false_rejects),
            "false_accept_n": len(false_accepts),
            "disagreement_question_n": len({row["rc_id"] for row in disagreements}),
            "by_contract": by_contract,
        }
    return output


def main() -> None:
    rows: list[dict[str, object]] = []
    answer_test_counts: Counter[str] = Counter()
    input_type_counts: Counter[str] = Counter()

    for source_file in CORPUS_FILES:
        root = ET.parse(source_file).getroot()
        for question in root.findall("question"):
            if question.get("type") != "stack":
                continue
            row = analyze_question(question, source_file)
            if not row["rc_id"]:
                raise SystemExit(f"STACK question without rc_id in {source_file}")
            rows.append(row)
            for node in question.findall("prt/node"):
                answer_test_counts[clean(node.findtext("answertest"))] += 1
            for input_node in question.findall("input"):
                if clean(input_node.findtext("type")) != "notes":
                    input_type_counts[clean(input_node.findtext("type"))] += 1

    rows.sort(key=lambda row: str(row["rc_id"]))
    ids = [str(row["rc_id"]) for row in rows]
    if len(rows) != EXPECTED_STACK_QUESTIONS:
        raise SystemExit(
            f"expected {EXPECTED_STACK_QUESTIONS} STACK questions, found {len(rows)}"
        )
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate STACK rc_id in canonical corpus")

    prt_rows = [row for row in rows if int(row["prt_count"]) > 0]
    prtless_count = len(rows) - len(prt_rows)
    if prtless_count != EXPECTED_PRTLESS_QUESTIONS:
        raise SystemExit(
            f"expected {EXPECTED_PRTLESS_QUESTIONS} PRT-less question, found {prtless_count}"
        )

    study_ids = {
        row["rc_id"]
        for row in csv.DictReader(STUDY_SELECTION.open(encoding="utf-8-sig"))
    }
    study_rows = [row for row in rows if row["rc_id"] in study_ids]
    if len(study_rows) != len(study_ids):
        missing = sorted(study_ids - {str(row["rc_id"]) for row in study_rows})
        raise SystemExit(f"study selection IDs missing from corpus: {missing}")

    study_answer_test_counts: Counter[str] = Counter()
    for row in study_rows:
        study_answer_test_counts.update(
            json.loads(str(row["answer_test_node_counts_json"]))
        )

    current_contracts: dict[str, bytes] = {}
    historical_contracts: dict[str, bytes] = {}
    for source_file in CORPUS_FILES:
        current_contracts.update(contract_fragments(source_file.read_bytes()))
        historical_contracts.update(contract_fragments(
            (STUDY_CORPUS_SNAPSHOT / source_file.name).read_bytes()))
    current_contract_digest = selected_contract_digest(current_contracts, study_ids)
    historical_contract_digest = selected_contract_digest(historical_contracts, study_ids)
    if current_contract_digest != historical_contract_digest:
        raise SystemExit(
            "selected questions' input/PRT contracts differ from the graded snapshot"
        )

    study_result_rows_all = list(csv.DictReader(STUDY_RESULTS.open(encoding="utf-8")))
    paper_scope = json.loads(STUDY_PAPER_SCOPE.read_text(encoding="utf-8"))
    scope_inputs = paper_scope.get("inputs", {})
    if (
        paper_scope.get("schema") != "study_paper_scope_v1"
        or scope_inputs.get(str(STUDY_RESULTS.relative_to(ROOT))) != sha256(STUDY_RESULTS)
    ):
        raise SystemExit("paper response scope is not bound to the study results")
    paper_roles = set(
        paper_scope.get("scope_decision", {}).get("paper_response_roles", [])
    )
    study_result_rows = [
        row for row in study_result_rows_all if row["kind"] in paper_roles
    ]
    if len(study_result_rows) != paper_scope.get("paper_scope", {}).get("responses"):
        raise SystemExit("paper response scope count differs from the filtered study rows")
    feature_rows = {str(row["rc_id"]): row for row in rows}
    if {row["rc_id"] for row in study_result_rows_all} != study_ids:
        raise SystemExit("study results and selected-question IDs differ")

    summary = {
        "schema": "grading_contract_audit_v1",
        "operational_definition": {
            "direct_equivalence_only": (
                "Every non-notes input maps one-to-one to one PRT containing one "
                "terminal AlgEquiv node; autosimplify is enabled, testoptions are "
                "empty, and true/false branches produce scores 1/0. Equivalent "
                "terminal score encodings (=1 versus +1, and =0 versus +/-0) "
                "are treated alike."
            ),
            "primary_denominator": (
                "The 1,603 canonical STACK questions that contain at least one PRT."
            ),
            "scope_note": (
                "This is a static structural audit. It does not prove that no other "
                "checker could reproduce a contract, and overlapping feature counts "
                "must not be summed. Input restrictions and feedback are excluded "
                "from the primary PRT-logic count and reported separately."
            ),
        },
        "corpus": {
            "stack_questions": len(rows),
            "questions_with_prt": len(prt_rows),
            "questions_without_prt": prtless_count,
            "prts": sum(int(row["prt_count"]) for row in rows),
            "answer_test_nodes": sum(int(row["node_count"]) for row in rows),
            "distinct_answer_test_types": len(answer_test_counts),
            "features_question_level": feature_summary(prt_rows, len(prt_rows)),
            "answer_test_nodes_by_type": dict(sorted(answer_test_counts.items())),
            "answer_inputs_by_type": dict(sorted(input_type_counts.items())),
        },
        "study_sample": {
            "questions": len(study_rows),
            "contract_snapshot": {
                "generation_contract_sha256": historical_contract_digest,
                "current_contract_sha256": current_contract_digest,
                "contracts_unchanged": True,
            },
            "features_question_level": feature_summary(study_rows, len(study_rows)),
            "answer_test_nodes_by_type": dict(sorted(study_answer_test_counts.items())),
            "checker_response_scope": {
                "response_roles": sorted(paper_roles),
                "responses": len(study_result_rows),
                "archived_roles_excluded": paper_scope.get(
                    "scope_decision", {}
                ).get("archived_response_roles", []),
            },
            "checker_diagnostics": checker_summary(study_result_rows, feature_rows),
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    primary = summary["corpus"]["features_question_level"][  # type: ignore[index]
        "prt_logic_beyond_direct_equivalence"
    ]
    print(
        f"Wrote {OUT_CSV.relative_to(ROOT)} and {OUT_JSON.relative_to(ROOT)}\n"
        f"PRT logic beyond direct equivalence: {primary['n']}/{len(prt_rows)} "
        f"({primary['percent']:.1f}%)"
    )


if __name__ == "__main__":
    main()
