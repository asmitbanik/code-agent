"""Rank issues easiest first."""

from agent_auto.contribute.issues import GitHubIssue
from agent_auto.contribute.rank import rank_issues


def test_rank_docs_before_complex() -> None:
    issues = [
        GitHubIssue(1, "Add JWT auth migration", "database auth", "u", labels=["backend"]),
        GitHubIssue(2, "Fix typo in README", "docs only", "u", labels=["documentation"]),
        GitHubIssue(3, "Implement product list endpoint", "add feature api", "u", labels=[]),
    ]
    ranked = rank_issues(issues)
    assert ranked[0].number == 2
    assert ranked[0].complexity == "docs"
    assert ranked[-1].complexity in {"complex", "standard"}
