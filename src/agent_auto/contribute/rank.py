"""Rank issues by complexity (easiest first)."""

from __future__ import annotations

from agent_auto.classify import analyze_task
from agent_auto.contribute.issues import GitHubIssue

COMPLEXITY_ORDER = {"docs": 0, "simple": 1, "standard": 2, "complex": 3}

EASY_LABEL_BOOST = {
    "good first issue",
    "good-first-issue",
    "documentation",
    "docs",
    "easy",
    "beginner",
    "help wanted",
}


def rank_issues(issues: list[GitHubIssue]) -> list[GitHubIssue]:
    ranked: list[tuple[int, int, GitHubIssue]] = []
    for issue in issues:
        text = f"{issue.title}\n{issue.body}\n" + " ".join(issue.labels)
        req = analyze_task(text)
        issue.complexity = req.complexity
        order = COMPLEXITY_ORDER.get(req.complexity, 2)
        labels = {lab.lower() for lab in issue.labels}
        # Soft boost: easy labels sort slightly earlier within same complexity
        boost = -1 if labels & EASY_LABEL_BOOST else 0
        ranked.append((order, boost, issue))
    ranked.sort(key=lambda t: (t[0], t[1], t[2].number))
    return [t[2] for t in ranked]
