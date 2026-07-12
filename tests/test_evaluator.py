"""Evaluator merge logic."""

from agent_auto.models import EvaluationPart, EvaluationResult


def test_evaluation_result_model() -> None:
    result = EvaluationResult(
        passed=False,
        tests=EvaluationPart(name="tests", passed=True, summary="ok"),
        browser=EvaluationPart(name="browser", passed=False, summary="missing text"),
        message="tests=PASS; browser=FAIL",
    )
    assert result.passed is False
    assert result.browser and result.browser.passed is False
