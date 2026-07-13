"""PR body template tests."""

from agent_auto.contribute.issues import GitHubIssue
from agent_auto.contribute.pr_body import build_pr_body, build_pr_title, infer_change_kind
from agent_auto.models import Subtask, TaskPlan


def test_pr_body_contains_fixes_and_sections() -> None:
    issue = GitHubIssue(42, "Broken login button", "The login button does nothing", "u")
    plan = TaskPlan(
        goal="Fix login button",
        needs=["Update login handler", "Add regression test"],
        subtasks=[Subtask(id="1", title="Fix handler", done_when="done", status="done")],
    )
    body = build_pr_body(
        issue=issue,
        plan=plan,
        evaluation=None,
        ux_summary="browser smoke passed",
        change_kind="bug fix",
    )
    assert "Fixes #42" in body
    assert "What kind of change" in body
    assert "bug fix" in body
    assert "[x] Exercised the reported user flow" in body


def test_pr_title() -> None:
    issue = GitHubIssue(7, "Add dark mode toggle", "", "u")
    assert "#7" in build_pr_title(issue, "feature")
    assert infer_change_kind(issue, None) in {"feature", "docs", "bug fix", "refactor", "chore"}
