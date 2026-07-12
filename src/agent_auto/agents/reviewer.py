"""Reviewer agent — approve or request changes; never edits files."""

from __future__ import annotations

from dataclasses import dataclass

from agent_auto.llm.client import LLMClient
from agent_auto.models import EvaluationResult, TaskPlan
from agent_auto.tools.git_ops import git_diff

REVIEWER_SYSTEM = (
    "You are the Reviewer agent. Do NOT write or edit code. "
    "Given the plan, git diff summary, and test results, return JSON: "
    '{"approved": bool, "feedback": string, "rework_subtask_ids": string[]}. '
    "Approve if the diff reasonably implements the plan and tests are acceptable."
)


@dataclass
class ReviewResult:
    approved: bool
    feedback: str
    rework_subtask_ids: list[str]


def run_reviewer(
    client: LLMClient,
    *,
    root,
    plan: TaskPlan,
    evaluation: EvaluationResult | None,
    complexity: str,
) -> ReviewResult:
    diff = git_diff(root)
    user = (
        f"COMPLEXITY: {complexity}\n"
        f"PLAN: {plan.model_dump_json()}\n"
        f"EVAL: {(evaluation.message if evaluation else 'n/a')}\n"
        f"TEST SUMMARY: {(evaluation.tests.summary[:1000] if evaluation and evaluation.tests else '')}\n"
        f"DIFF STAT:\n{diff.get('stat', '')}\n"
        f"DIFF (truncated):\n{(diff.get('diff') or '')[:4000]}\n"
    )
    data = client.generate_json(system=REVIEWER_SYSTEM, user=user, max_tokens=800)
    approved = bool(data.get("approved"))
    # Stricter for complex: require evaluation passed when tests were run
    if complexity == "complex" and evaluation and not evaluation.passed:
        approved = False
    rework = data.get("rework_subtask_ids") or []
    if isinstance(rework, str):
        rework = [rework]
    return ReviewResult(
        approved=approved,
        feedback=str(data.get("feedback") or ""),
        rework_subtask_ids=[str(x) for x in rework],
    )
