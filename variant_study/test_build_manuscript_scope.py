"""Focused tests for the manuscript response-scope aggregation."""

from build_manuscript_scope import checker_summary, key_digest, response_key


def row(
    *,
    rc_id: str,
    status: str,
    string_eq: str,
    sympy_eq: str = "",
    math_verify_eq: str = "",
) -> dict[str, str]:
    return {
        "model": "model-a",
        "rc_id": rc_id,
        "kind": "fresh",
        "seed": "1",
        "rep": "0",
        "status": status,
        "string_eq": string_eq,
        "sympy_eq": sympy_eq,
        "math_verify_eq": math_verify_eq,
    }


def test_response_key_and_digest_are_order_independent() -> None:
    left = row(rc_id="rc-a", status="correct", string_eq="1")
    right = row(rc_id="rc-b", status="wrong", string_eq="0")
    assert response_key(left) == ("model-a", "rc-a", "fresh", "1", "0")
    assert key_digest([left, right]) == key_digest([right, left])


def test_checker_summary_accounts_for_coverage_and_contract_class() -> None:
    rows = [
        row(
            rc_id="rc-direct",
            status="correct",
            string_eq="0",
            sympy_eq="1",
            math_verify_eq="1",
        ),
        row(
            rc_id="rc-rich",
            status="wrong",
            string_eq="0",
            sympy_eq="",
            math_verify_eq="",
        ),
        row(
            rc_id="rc-rich",
            status="syntax_invalid",
            string_eq="",
        ),
    ]
    classes = {
        "rc-direct": "direct_equivalence_only",
        "rc-rich": "richer_prt_logic",
    }
    summary = checker_summary(rows, classes)
    assert summary["decisive_stack_outcomes"] == 2
    assert summary["methods"]["string_eq"]["coverage_n"] == 2
    assert summary["methods"]["string_eq"]["false_reject_n"] == 1
    assert summary["methods"]["sympy_eq"]["coverage_n"] == 1
    assert (
        summary["methods"]["sympy_eq"]["by_contract"]
        ["direct_equivalence_only"]["conditional_agreement_percent"]
        == 100.0
    )
