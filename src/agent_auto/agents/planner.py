"""Planner agent — produces structured plans only; never edits files."""

from __future__ import annotations

from agent_auto.classify import TaskRequirements
from agent_auto.llm.client import LLMClient
from agent_auto.models import RepoContext, Subtask, TaskPlan
from agent_auto.rag.retriever import ContextPack

PLANNER_SYSTEM = (
    "You are the Planner agent. Do NOT write code. "
    "Return JSON only with keys: goal, needs (string array checklist), "
    "subtasks (array of {id,title,done_when,files_hint}), risks, "
    "success_criteria, verify ({run_tests:bool, browser:bool}), browser_checks. "
    "Keep subtasks small and actionable."
)


def run_planner(
    client: LLMClient,
    *,
    task: str,
    context: RepoContext,
    requirements: TaskRequirements,
    context_pack: ContextPack | None = None,
    max_subtasks: int = 8,
) -> TaskPlan:
    retrieved = context_pack.as_prompt_block(max_chars=6_000) if context_pack else ""
    user = (
        f"TASK: {task}\n"
        f"COMPLEXITY: {requirements.complexity}\n"
        f"STACK: {context.stack_notes}\n"
        f"TOP: {', '.join(context.top_level[:25])}\n"
        f"MAX_SUBTASKS: {max_subtasks}\n"
        f"RETRIEVED CONTEXT:\n{retrieved}\n"
    )
    data = client.generate_json(system=PLANNER_SYSTEM, user=user, max_tokens=1500)
    return _parse(data, max_subtasks, task)


def _parse(data: dict, max_subtasks: int, task: str) -> TaskPlan:
    subtasks: list[Subtask] = []
    for i, item in enumerate((data.get("subtasks") or [])[:max_subtasks]):
        if not isinstance(item, dict):
            continue
        hints = item.get("files_hint") or []
        if isinstance(hints, str):
            hints = [hints]
        subtasks.append(
            Subtask(
                id=str(item.get("id") or str(i + 1)),
                title=str(item.get("title") or f"Step {i + 1}"),
                done_when=str(item.get("done_when") or "completed"),
                files_hint=[str(h) for h in hints],
                status="pending",
            )
        )
    if not subtasks:
        subtasks = [
            Subtask(id="1", title="Implement task", done_when="done", status="pending")
        ]
    verify = data.get("verify") if isinstance(data.get("verify"), dict) else {}
    return TaskPlan(
        goal=str(data.get("goal") or task[:240]),
        needs=[str(n) for n in (data.get("needs") or [])],
        risks=[str(r) for r in (data.get("risks") or [])],
        success_criteria=[str(c) for c in (data.get("success_criteria") or ["task done"])],
        subtasks=subtasks,
        browser_checks=[str(c) for c in (data.get("browser_checks") or [])],
        verify={
            "run_tests": bool(verify.get("run_tests", True)),
            "browser": bool(verify.get("browser", False)),
        },
    )
