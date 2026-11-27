#!/usr/bin/env python3
"""Recompute the paper's numbers for the randomized-instance study.

Run from this folder:

    python recompute_paper_numbers.py

The study record (``results.csv``) holds 1,610 responses. The paper analyzes
1,440 of them: the responses to the four instances of each question
(``kind = fresh``) and the repeated responses to unchanged prompts
(``kind = replicate``). The 170 responses at seeds retained in source-course
exports (``kind = anchor``) stay in the record and are not part of the
paper's aggregates.

``analyze.py`` in this folder is the prespecified analysis of the complete
grid, so its checker totals include those 170 responses. This script applies
the paper's scope with the functions of ``build_manuscript_scope.py`` and
``analyze_outcome_decomposition.py`` and reads only files of this repository:

* ``results.csv`` and ``grade_manifest.json`` (primary grading run);
* ``../grading_contract_audit/question_features.csv`` (which questions have
  the strict direct-equivalence form);
* ``sensitivity/outer_brace_regrade/results.csv`` (the named sensitivity run).

It prints the numbers of Section 6.2, Figure 3 and Tables 10, 11 and 13 and
compares everything it computes with the shipped ``paper_scope_summary.json``
and ``outcome_decomposition.json``. Exit status 0 means that every compared
value is identical; 1 means that at least one differs. It writes nothing.
"""
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

import analyze_outcome_decomposition as decomposition  # noqa: E402
import build_manuscript_scope as scope  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results.csv"
MANIFEST = HERE / "grade_manifest.json"
ANALYSIS = HERE / "analysis.json"
FEATURES = HERE.parent / "grading_contract_audit" / "question_features.csv"
REGRADE = HERE / "sensitivity" / "outer_brace_regrade" / "results.csv"
SHIPPED_SCOPE = HERE / "paper_scope_summary.json"
SHIPPED_DECOMPOSITION = HERE / "outcome_decomposition.json"

CHECKER_NAMES = {"string_eq": "normalized exact match",
                 "sympy_eq": "SymPy", "math_verify_eq": "Math-Verify"}
PROFILE_ORDER = (
    "gpt-5-2025-08-07", "qwen3:32b", "gemma4:31b",
    "hf.co/unsloth/GLM-Z1-32B-0414-GGUF:Q4_K_M",
    "hf.co/unsloth/GLM-4-32B-0414-GGUF:Q4_K_M",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def brace_changes(raw_rows, paper_rows):
    """Responses whose status or score differs in the outer-brace regrade."""
    primary = {scope.response_key(row): row for row in raw_rows}
    regrade = {scope.response_key(row): row for row in read_rows(REGRADE)}
    if set(primary) != set(regrade):
        raise SystemExit("the regrade does not cover the same responses")

    def outcome(row):
        return row["status"], (None if row["score"] == ""
                               else float(row["score"]))

    changed = [key for key in primary
               if outcome(primary[key]) != outcome(regrade[key])]
    paper_keys = {scope.response_key(row) for row in paper_rows}
    return {
        "changed_responses_all_roles": len(changed),
        "changed_responses_paper_scope": sum(
            key in paper_keys for key in changed),
        "changed_responses_archived_role": sum(
            key not in paper_keys for key in changed),
    }


def recompute():
    raw_rows = read_rows(RESULTS)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["sha256"]["results"] != sha256(RESULTS) \
            or manifest["rows"] != len(raw_rows):
        raise SystemExit("results.csv is not the file named in "
                         "grade_manifest.json")
    paper_rows = [row for row in raw_rows if row["kind"] in scope.PAPER_KINDS]
    archived_rows = [row for row in raw_rows
                     if row["kind"] in scope.ARCHIVED_KINDS]
    if len(paper_rows) + len(archived_rows) != len(raw_rows):
        raise SystemExit("unexpected response role in results.csv")

    scope.QUESTION_FEATURES = FEATURES
    contract_class = scope.load_contract_classes(
        {row["rc_id"] for row in raw_rows})
    models = sorted({row["model"] for row in raw_rows})
    return {
        "frozen_grid": {
            "responses": len(raw_rows),
            "models": len(models),
            "response_roles": dict(sorted(
                Counter(row["kind"] for row in raw_rows).items())),
            "response_key_sha256": scope.key_digest(raw_rows),
        },
        "archived_source_seed_comparison": {
            "responses": len(archived_rows),
            "questions": len({row["rc_id"] for row in archived_rows}),
            "models": len({row["model"] for row in archived_rows}),
            "response_key_sha256": scope.key_digest(archived_rows),
            "question_ids": sorted({row["rc_id"] for row in archived_rows}),
        },
        "paper_scope": {
            "responses": len(paper_rows),
            "questions": len({row["rc_id"] for row in paper_rows}),
            "models": len(models),
            "responses_per_model": 288,
            "primary_instance_responses_per_model": 240,
            "same_prompt_additional_responses_per_model": 48,
            "response_key_sha256": scope.key_digest(paper_rows),
            "status_counts": scope.status_summary(paper_rows),
            "models_detail": scope.per_model_summary(paper_rows),
            "checker_diagnostics": scope.checker_summary(
                paper_rows, contract_class),
        },
        "brace_sensitivity": brace_changes(raw_rows, paper_rows),
    }


def compare(recomputed, decomposed):
    """Differences between recomputed values and the shipped summaries."""
    shipped = json.loads(SHIPPED_SCOPE.read_text(encoding="utf-8"))
    differences = []

    def check(label, ours, theirs):
        if ours != theirs:
            differences.append(label)

    check("frozen_grid", recomputed["frozen_grid"], shipped["frozen_grid"])
    archived = dict(shipped["archived_source_seed_comparison"])
    archived.pop("prespecified_analysis_preserved_at")
    check("archived_source_seed_comparison",
          recomputed["archived_source_seed_comparison"], archived)
    paper = dict(shipped["paper_scope"])
    brace = paper.pop("brace_sensitivity")
    check("paper_scope", recomputed["paper_scope"], paper)
    check("brace_sensitivity", recomputed["brace_sensitivity"], brace)
    # The summary names its three inputs, all in this repository, with
    # their hashes.
    check("input hashes", {f"variant_study/{path.name}": sha256(path)
                           for path in (ANALYSIS, MANIFEST, RESULTS)},
          shipped["inputs"])

    shipped_decomposition = json.loads(
        SHIPPED_DECOMPOSITION.read_text(encoding="utf-8"))
    for key in ("schema", "analysis_role", "primary_rule", "definitions",
                "models"):
        check(f"outcome_decomposition.{key}", decomposed[key],
              shipped_decomposition[key])
    check("outcome_decomposition input hash",
          list(decomposed["inputs"].values()),
          list(shipped_decomposition["inputs"].values()))
    return differences


def report(recomputed, decomposed):
    paper = recomputed["paper_scope"]
    grid = recomputed["frozen_grid"]
    status = paper["status_counts"]
    print(f"Responses in the study record: {grid['responses']:,} "
          f"({grid['response_roles']})")
    print(f"Responses in the scope of the paper: {paper['responses']:,} on "
          f"{paper['questions']} questions; archived and excluded: "
          f"{recomputed['archived_source_seed_comparison']['responses']}")
    print(f"Outcomes: full credit {status.get('correct', 0):,}, zero "
          f"{status.get('wrong', 0)}, STACK-ungradable "
          f"{status.get('syntax_invalid', 0)}, format failure "
          f"{status.get('format_failure', 0)}")
    print("\nPer profile (240 instance responses, 60 questions):")
    print(f"  {'profile':<13}{'full credit':>16}{'all four':>10}"
          f"{'mixed':>7}{'mixed gradable':>16}{'invalid-only':>14}"
          f"{'format-only':>13}")
    for model in PROFILE_ORDER:
        detail = paper["models_detail"][model]
        parts = decomposed["models"][model]
        categories = parts["categories"]
        mixed = categories["mixed_gradable"] + categories["mixed_invalid_only"]
        full = (f"{detail['primary_full_credit_n']} "
                f"({detail['primary_full_credit_percent']}%)")
        print(f"  {parts['label']:<13}{full:>16}"
              f"{categories['all_four_full_credit']:>10}{mixed:>7}"
              f"{categories['mixed_gradable']:>16}"
              f"{categories['mixed_invalid_only']:>14}"
              f"{parts['mixed_format_failure_only']:>13}")
    checkers = paper["checker_diagnostics"]
    print(f"\nSecondary diagnostics on {checkers['decisive_stack_outcomes']:,} "
          "responses with full or zero credit:")
    for name in ("string_eq", "sympy_eq", "math_verify_eq"):
        method = checkers["methods"][name]
        richer = method["by_contract"]["richer_prt_logic"]
        print(f"  {CHECKER_NAMES[name]:<23} covered {method['coverage_n']:>5,} "
              f"({method['coverage_percent']}%), agrees "
              f"{method['agreement_n']:>5,} "
              f"({method['conditional_agreement_percent']}%), rejects "
              f"full credit {method['false_reject_n']:>3}, accepts zero "
              f"credit {method['false_accept_n']}; richer contracts: "
              f"{richer['disagreement_n']} of {richer['coverage_n']} differ")
    brace = recomputed["brace_sensitivity"]
    print(f"\nOuter-brace regrade: {brace['changed_responses_all_roles']} "
          f"responses change ({brace['changed_responses_paper_scope']} in "
          "the scope of the paper)")


def main():
    recomputed = recompute()
    decomposed = decomposition.analyze(RESULTS)
    report(recomputed, decomposed)
    differences = compare(recomputed, decomposed)
    if differences:
        print("\nDIFFERENT from the shipped summaries: "
              + "; ".join(differences), file=sys.stderr)
        raise SystemExit(1)
    print("\nOK: identical to paper_scope_summary.json and "
          "outcome_decomposition.json")


if __name__ == "__main__":
    main()
