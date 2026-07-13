"""Issue eligibility filters for contribute mode."""

from __future__ import annotations

from agent_auto.contribute.issues import GitHubIssue

SKIP_LABELS = {
    "rfc",
    "discussion",
    "wontfix",
    "invalid",
    "duplicate",
    "question",
    "meta",
}


def is_eligible(issue: GitHubIssue, *, me: str) -> tuple[bool, str | None]:
    labels = {lab.lower() for lab in issue.labels}
    if labels & SKIP_LABELS:
        return False, f"skip label: {sorted(labels & SKIP_LABELS)}"

    # Already have our own open PR for this issue
    for pr in issue.linked_prs:
        if pr.state == "OPEN" and pr.author.lower() == me.lower():
            return False, f"already have open PR #{pr.number}"

    # Assignee has an open PR referencing this issue -> skip
    assignees = {a.lower() for a in issue.assignee_logins}
    if assignees:
        for pr in issue.linked_prs:
            if pr.state == "OPEN" and pr.author.lower() in assignees:
                return False, (
                    f"assignee {pr.author} already has open PR #{pr.number}"
                )

    return True, None


def filter_eligible(issues: list[GitHubIssue], *, me: str) -> list[GitHubIssue]:
    kept: list[GitHubIssue] = []
    for issue in issues:
        ok, reason = is_eligible(issue, me=me)
        if ok:
            kept.append(issue)
        else:
            issue.skip_reason = reason
    return kept
