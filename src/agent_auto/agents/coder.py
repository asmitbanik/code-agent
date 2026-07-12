"""Coder agent — implements one subtask using retrieved context + tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console

from agent_auto.config import Settings
from agent_auto.llm.client import LLMClient
from agent_auto.models import RepoContext, Subtask, TaskPlan
from agent_auto.rag.retriever import ContextPack
from agent_auto.report.writer import ReportWriter
from agent_auto.tools.registry import ToolRuntime, build_openai_tools, truncate_result

CODER_SYSTEM = (
    "You are the Coder agent. Implement ONLY the current subtask. "
    "Use tools to read/edit files. Prefer apply_patch. "
    "Call mark_subtask_done when the subtask is complete, then finish_task. "
    "Do not push or force-reset git."
)


def run_coder(
    client: LLMClient,
    *,
    root: Path,
    task: str,
    context: RepoContext,
    plan: TaskPlan,
    subtask: Subtask,
    context_pack: ContextPack,
    settings: Settings,
    writer: ReportWriter,
    console: Console,
    max_steps: int = 8,
) -> bool:
    runtime = ToolRuntime(
        root=root,
        context=context,
        plan=plan,
        settings=settings,
        artifacts_dir=writer.run_dir / "artifacts",
        skip_browser=True,
        skip_tests=True,
    )
    tools = build_openai_tools()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"OVERALL TASK: {task}\n"
                f"SUBTASK [{subtask.id}]: {subtask.title}\n"
                f"DONE WHEN: {subtask.done_when}\n"
                f"FILES HINT: {', '.join(subtask.files_hint) or 'n/a'}\n"
                f"STACK: {context.stack_notes}\n"
                f"RETRIEVED CODE:\n{context_pack.as_prompt_block()}\n"
                "Implement this subtask now."
            ),
        }
    ]

    for step in range(1, max_steps + 1):
        console.print(f"    coder step {step}")
        writer.log(f"coder subtask={subtask.id} step={step}")
        msg = client.chat_with_tools(
            system=CODER_SYSTEM,
            messages=messages,
            tools=tools,
            temperature=0.2,
            max_tokens=1800,
        )
        tool_calls = msg.get("tool_calls") or []
        messages.append(msg)
        if not tool_calls:
            if runtime.finish_requested or subtask.status == "done":
                return True
            messages.append(
                {
                    "role": "user",
                    "content": "Continue with tools, or call mark_subtask_done / finish_task.",
                }
            )
            continue

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            console.print(f"      tool: {name}")
            result = runtime.dispatch(name, args)
            if name == "mark_subtask_done" and result.get("ok"):
                subtask.status = "done"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or name,
                    "name": name,
                    "content": truncate_result(result),
                }
            )

        if runtime.finish_requested or subtask.status == "done":
            subtask.status = "done"
            return True

    return subtask.status == "done"
