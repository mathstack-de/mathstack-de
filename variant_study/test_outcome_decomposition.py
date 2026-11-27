"""Tests for the frozen randomized-instance study outcome decomposition."""

import pytest

from analyze_outcome_decomposition import classify_template


def test_all_four_full_credit() -> None:
    assert classify_template(["correct"] * 4) == "all_four_full_credit"


def test_no_full_credit() -> None:
    assert classify_template([
        "wrong", "syntax_invalid", "format_failure", "wrong"
    ]) == "no_full_credit"


def test_mixed_gradable_requires_a_non_full_credit_gradable_response() -> None:
    assert classify_template([
        "correct", "wrong", "syntax_invalid", "correct"
    ]) == "mixed_gradable"


def test_mixed_invalid_only_contains_no_gradable_rejection() -> None:
    assert classify_template([
        "correct", "format_failure", "syntax_invalid", "correct"
    ]) == "mixed_invalid_only"


def test_unknown_status_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown outcome"):
        classify_template(["correct", "correct", "correct", "mystery"])
