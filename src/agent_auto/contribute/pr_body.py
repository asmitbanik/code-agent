"""Structured PR body matching common OSS contributor templates."""

from __future__ import annotations

from agent_auto.contribute.issues import GitHubIssue
from agent_auto.models import EvaluationResult, TaskPlan


def infer_change_kind(issue: GitHubIssue, plan: TaskPlan | None) -> str:
    text = f"{issue.title} {issue.body} {' '.join(issue.labels)}".lower()
    if any(x in text for x in ("doc", "readme")):
        return "docs"
    if any(x in text for x in ("bug", "fix", "error", "crash", "broken")):
        return "bug fix"
    if any(x in text for x in ("refactor", "cleanup")):
        return "refactor"
    if plan and plan.needs:
        return "feature"
    return "feature"


def build_pr_body(
    *,
    issue: GitHubIssue,
    plan: TaskPlan | None,
    evaluation: EvaluationResult | None,
    ux_summary: str,
    change_kind: str | None = None,
    breaking: bool = False,
    polished_summary: str | None = None,
    polished_why: list[str] | None = None,
) -> str:
    kind = change_kind or infer_change_kind(issue, plan)
    needs = (plan.needs if plan else []) or []
    subtasks = [f"- {s.title}" for s in (plan.subtasks if plan else [])]
    what = needs or subtasks or [f"- Address issue #{issue.number}: {issue.title}"]
    why = polished_why or [
        f"- Resolves reported problem in #{issue.number}",
        "- Improves maintainability / user experience for contributors and users",
    ]
    summary = polished_summary or (
        plan.goal if plan else f"Implements a fix/feature for issue #{issue.number}."
    )
    ux_ok = "passed" in ux_summary.lower() or "pass" in ux_summary.lower()
    eval_msg = evaluation.message if evaluation else "n/a"

    lines = [
        "## What kind of change does this PR introduce?",
        kind,
        "",
        "## Issue Number",
        f"Fixes #{issue.number}",
        "",
        "## Summary",
        summary,
        "",
        "## What this PR does",
        *what,
        "",
        "## Why this is needed",
        *why,
        "",
        "## Does this PR introduce a breaking change?",
        "Yes" if breaking else "No",
        "",
        "- Existing public APIs remain compatible unless noted above.",
        "",
        "## Checklist",
        "",
        "### Verification",
        f"- [{'x' if ux_ok else ' '}] Exercised the reported user flow in a local browser/API smoke",
        f"- [{'x' if evaluation and evaluation.passed else ' '}] Local verification: {eval_msg}",
        "- [ ] Full suite left to CI where noted",
        "",
        "### Notes",
        f"UX/API notes: {ux_summary}",
        "",
        "_Opened by agent-auto contribute mode._",
    ]
    return "\n".join(lines)


def build_pr_title(issue: GitHubIssue, change_kind: str | None = None) -> str:
    kind = change_kind or infer_change_kind(issue, None)
    prefix = {
        "bug fix": "fix",
        "feature": "feat",
        "docs": "docs",
        "refactor": "refactor",
        "chore": "chore",
    }.get(kind, "chore")
    title = issue.title.strip()
    if len(title) > 72:
        title = title[:69] + "..."
    return f"{prefix}: {title} (#{issue.number})"
