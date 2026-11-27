"""Focused tests for the grading-contract classifier."""

from pathlib import Path
import xml.etree.ElementTree as ET

from analyze_grading_contracts import analyze_question


def question_xml(
    *,
    answer_test: str = "AlgEquiv",
    sans: str = "ans1",
    test_options: str = "",
    true_score: str = "1",
    true_mode: str = "=",
    false_score: str = "0",
    false_mode: str = "=",
    true_next: str = "-1",
    extra_node: str = "",
) -> ET.Element:
    return ET.fromstring(
        f"""
        <question type="stack">
          <idnumber>rc-test</idnumber>
          <name><text>Test</text></name>
          <input>
            <name>ans1</name><type>algebraic</type><forbidfloat>1</forbidfloat>
          </input>
          <prt>
            <name>prt1</name><autosimplify>1</autosimplify>
            <node>
              <name>0</name><answertest>{answer_test}</answertest>
              <sans>{sans}</sans><tans>ta1</tans>
              <testoptions>{test_options}</testoptions>
              <truescoremode>{true_mode}</truescoremode><truescore>{true_score}</truescore>
              <truenextnode>{true_next}</truenextnode>
              <falsescoremode>{false_mode}</falsescoremode><falsescore>{false_score}</falsescore>
              <falsenextnode>-1</falsenextnode>
            </node>
            {extra_node}
          </prt>
        </question>
        """
    )


def analyze(question: ET.Element) -> dict[str, object]:
    return analyze_question(question, Path("synthetic.xml"))


def test_single_terminal_binary_algequiv_is_direct() -> None:
    row = analyze(question_xml())
    assert row["direct_equivalence_only"] is True
    assert row["prt_logic_beyond_direct_equivalence"] is False


def test_equivalent_additive_binary_score_encoding_is_direct() -> None:
    row = analyze(question_xml(true_mode="+", false_mode="-"))
    assert row["direct_equivalence_only"] is True
    assert row["prt_logic_beyond_direct_equivalence"] is False


def test_non_algequiv_answer_test_is_richer() -> None:
    row = analyze(question_xml(answer_test="NumAbsolute"))
    assert row["has_non_alg_equiv_test"] is True
    assert row["prt_logic_beyond_direct_equivalence"] is True


def test_derived_student_expression_is_richer() -> None:
    row = analyze(question_xml(sans="diff(ans1,x)"))
    assert row["has_derived_student_expression"] is True
    assert row["prt_logic_beyond_direct_equivalence"] is True


def test_branching_or_partial_credit_is_richer() -> None:
    row = analyze(question_xml(true_score="0.5", true_next="1"))
    assert row["has_branching"] is True
    assert row["has_partial_credit_score"] is True
    assert row["prt_logic_beyond_direct_equivalence"] is True


def test_reversed_binary_scores_are_richer() -> None:
    row = analyze(question_xml(true_score="0", false_score="1"))
    assert row["prt_logic_beyond_direct_equivalence"] is True


def test_multiple_nodes_or_test_options_are_richer() -> None:
    extra_node = """
      <node>
        <name>1</name><answertest>AlgEquiv</answertest>
        <sans>ans1</sans><tans>ta2</tans><testoptions></testoptions>
        <truescoremode>=</truescoremode><truescore>1</truescore>
        <truenextnode>-1</truenextnode>
        <falsescoremode>=</falsescoremode><falsescore>0</falsescore>
        <falsenextnode>-1</falsenextnode>
      </node>
    """
    multi = analyze(question_xml(extra_node=extra_node))
    option = analyze(question_xml(test_options="x"))
    assert multi["has_multi_node_prt"] is True
    assert multi["prt_logic_beyond_direct_equivalence"] is True
    assert option["has_test_options"] is True
    assert option["prt_logic_beyond_direct_equivalence"] is True
