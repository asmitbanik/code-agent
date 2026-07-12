"""Task planning — only used when heuristic planner is disabled."""

from __future__ import annotations

from agent_auto.llm.client import LLMClient
from agent_auto.models import RepoContext, Subtask, TaskPlan

PLAN_SYSTEM = (
    "Plan an autonomous coding task. Return JSON with keys: "
    "goal, success_criteria (array), browser_checks (array), "
    "subtasks (array of {id,title,done_when}). Keep subtasks few."
)


def create_plan(
    client: LLMClient,
    *,
    task: str,
    context: RepoContext,
    max_subtasks: int,
) -> TaskPlan:
    user = (
        f"TASK: {task}\nMAX_SUBTASKS: {max_subtasks}\n"
        f"STACK: {context.stack_notes}\n"
        f"TOP: {', '.join(context.top_level[:30])}\n"
    )
    data = client.generate_json(system=PLAN_SYSTEM, user=user, max_tokens=1200)
    return _parse_plan(data, max_subtasks)


def replan(
    client: LLMClient,
    *,
    task: str,
    context: RepoContext,
    current: TaskPlan,
    failure_feedback: str,
    max_subtasks: int,
) -> TaskPlan:
    user = (
        f"TASK: {task}\nFEEDBACK: {failure_feedback[:2000]}\n"
        f"CURRENT: {current.model_dump_json()}\n"
        f"STACK: {context.stack_notes}\nRevise remaining plan."
    )
    data = client.generate_json(system=PLAN_SYSTEM, user=user, max_tokens=1200)
    return _parse_plan(data, max_subtasks)


def _parse_plan(data: dict, max_subtasks: int) -> TaskPlan:
    subtasks_raw = data.get("subtasks") or []
    subtasks: list[Subtask] = []
    for i, item in enumerate(subtasks_raw[:max_subtasks]):
        if not isinstance(item, dict):
            continue
        subtasks.append(
            Subtask(
                id=str(item.get("id") or str(i + 1)),
                title=str(item.get("title") or f"Step {i + 1}"),
                done_when=str(item.get("done_when") or "completed"),
                status=str(item.get("status") or "pending"),
            )
        )
    criteria = [str(c) for c in (data.get("success_criteria") or [])]
    if not any("test" in c.lower() for c in criteria):
        criteria.append("tests pass")
    return TaskPlan(
        goal=str(data.get("goal") or "Complete the task"),
        success_criteria=criteria,
        subtasks=subtasks,
        browser_checks=[str(c) for c in (data.get("browser_checks") or [])],
    )
