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
    "Use at most 3 tool calls per turn. Prefer apply_patch over write_file. "
    "Read a file before editing. Call mark_subtask_done when done. "
    "Do not create unrelated files. Do not push or force-reset git."
)

MAX_TOOL_CALLS_PER_TURN = 3
MAX_HISTORY_MESSAGES = 12


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return messages
    # Keep first user brief + recent tail
    head = messages[:1]
    tail = messages[-(MAX_HISTORY_MESSAGES - 1) :]
    return head + tail


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
    # Keep prompt small for Groq TPM limits
    task_brief = task if len(task) <= 1500 else task[:1500] + "\n[truncated]"
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"TASK: {task_brief}\n"
                f"SUBTASK [{subtask.id}]: {subtask.title}\n"
                f"DONE WHEN: {subtask.done_when}\n"
                f"FILES HINT: {', '.join(subtask.files_hint) or 'n/a'}\n"
                f"STACK: {context.stack_notes}\n"
                f"CODE:\n{context_pack.as_prompt_block(max_chars=4_000)}\n"
                "Implement now. Max 3 tools this turn."
            ),
        }
    ]

    for step in range(1, max_steps + 1):
        console.print(f"    coder step {step}")
        writer.log(f"coder subtask={subtask.id} step={step}")
        messages = _compact_messages(messages)
        try:
            msg = client.chat_with_tools(
                system=CODER_SYSTEM,
                messages=messages,
                tools=tools,
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001
            # On context overflow, reset history and retry once
            console.print(f"      [yellow]coder LLM error, compacting:[/yellow] {exc}")
            messages = [
                {
                    "role": "user",
                    "content": (
                        f"SUBTASK [{subtask.id}]: {subtask.title}\n"
                        f"DONE WHEN: {subtask.done_when}\n"
                        f"CODE:\n{context_pack.as_prompt_block(max_chars=3_000)}\n"
                        "Continue with at most 3 tools, then mark_subtask_done."
                    ),
                }
            ]
            msg = client.chat_with_tools(
                system=CODER_SYSTEM,
                messages=messages,
                tools=tools,
                temperature=0.2,
                max_tokens=1200,
            )

        tool_calls = list(msg.get("tool_calls") or [])[:MAX_TOOL_CALLS_PER_TURN]
        # Drop excess tool_calls from assistant message to keep transcript valid
        if msg.get("tool_calls") and len(msg["tool_calls"]) > MAX_TOOL_CALLS_PER_TURN:
            msg = dict(msg)
            msg["tool_calls"] = tool_calls
        messages.append(msg)

        if not tool_calls:
            if runtime.finish_requested or subtask.status == "done":
                return True
            messages.append(
                {
                    "role": "user",
                    "content": "Use up to 3 tools, or call mark_subtask_done / finish_task.",
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
            # Cap write payloads
            if name == "write_file" and isinstance(args.get("content"), str):
                if len(args["content"]) > 20_000:
                    args["content"] = args["content"][:20_000]
            console.print(f"      tool: {name}")
            result = runtime.dispatch(name, args)
            if name == "mark_subtask_done" and result.get("ok"):
                subtask.status = "done"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or name,
                    "name": name,
                    "content": truncate_result(result, limit=2_500),
                }
            )

        if runtime.finish_requested or subtask.status == "done":
            subtask.status = "done"
            return True

    return subtask.status == "done"
