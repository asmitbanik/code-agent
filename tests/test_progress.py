"""Progress gate tests."""

from pathlib import Path

from agent_auto.contribute.progress import progress_ratio, should_claim
from agent_auto.models import EvaluationPart, EvaluationResult, Subtask, TaskPlan


def test_should_claim_when_majority_done(tmp_path: Path) -> None:
    # empty git-less dir: meaningful_diff false, but high subtask+ux can still pass
    plan = TaskPlan(
        goal="x",
        subtasks=[
            Subtask(id="1", title="a", done_when="d", status="done"),
            Subtask(id="2", title="b", done_when="d", status="done"),
        ],
    )
    ev = EvaluationResult(
        passed=True,
        tests=EvaluationPart(name="tests", passed=True, summary="ok"),
        message="ok",
    )
    ratio = progress_ratio(root=tmp_path, plan=plan, evaluation=ev, ux_passed=True)
    assert ratio >= 0.5
    assert should_claim(root=tmp_path, plan=plan, evaluation=ev, ux_passed=True)
