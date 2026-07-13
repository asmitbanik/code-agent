"""Eligibility unit tests."""

from agent_auto.contribute.eligibility import is_eligible
from agent_auto.contribute.issues import GitHubIssue, IssueAssignee, LinkedPR


def _issue(**kwargs) -> GitHubIssue:
    base = dict(
        number=1,
        title="Bug",
        body="fix it",
        url="https://github.com/o/r/issues/1",
    )
    base.update(kwargs)
    return GitHubIssue(**base)


def test_skip_when_assignee_has_open_pr() -> None:
    issue = _issue(
        assignees=[IssueAssignee(login="alice")],
        linked_prs=[LinkedPR(number=9, url="u", author="alice", state="OPEN")],
    )
    ok, reason = is_eligible(issue, me="me")
    assert ok is False
    assert reason and "alice" in reason


def test_allow_when_assignee_without_pr() -> None:
    issue = _issue(assignees=[IssueAssignee(login="alice")])
    ok, reason = is_eligible(issue, me="me")
    assert ok is True
    assert reason is None


def test_skip_own_open_pr() -> None:
    issue = _issue(
        linked_prs=[LinkedPR(number=3, url="u", author="me", state="OPEN")],
    )
    ok, _ = is_eligible(issue, me="me")
    assert ok is False


def test_skip_rfc_label() -> None:
    issue = _issue(labels=["RFC"])
    ok, reason = is_eligible(issue, me="me")
    assert ok is False
    assert reason and "rfc" in reason.lower()
