"""Act -> evaluate -> refine loop (used only for non-docs tasks)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console

from agent_auto.config import Settings
from agent_auto.llm.client import LLMClient
from agent_auto.models import EvaluationResult, RepoContext, TaskPlan
from agent_auto.planner.planner import replan
from agent_auto.report.writer import ReportWriter
from agent_auto.tools.registry import ToolRuntime, build_openai_tools, truncate_result
from agent_auto.verify.evaluator import evaluate

LOOP_SYSTEM = (
    "Autonomous coding agent. Use tools to edit code. "
    "Prefer apply_patch. Call finish_task when done. "
    "Never force-push or reset --hard. Stay in the workspace."
)


class LoopEngine:
    def __init__(
        self,
        *,
        client: LLMClient,
        root: Path,
        task: str,
        context: RepoContext,
        plan: TaskPlan,
        settings: Settings,
        writer: ReportWriter,
        console: Console,
        skip_browser: bool = False,
        skip_tests: bool = False,
    ) -> None:
        self.client = client
        self.root = root
        self.task = task
        self.context = context
        self.plan = plan
        self.settings = settings
        self.writer = writer
        self.console = console
        self.skip_browser = skip_browser or settings.agent_skip_browser
        self.skip_tests = skip_tests
        self.runtime = ToolRuntime(
            root=root,
            context=context,
            plan=plan,
            settings=settings,
            artifacts_dir=writer.run_dir / "artifacts",
            skip_browser=self.skip_browser,
            skip_tests=self.skip_tests,
        )
        self.last_evaluation: EvaluationResult | None = None
        self.iterations = 0

    def run(self) -> tuple[bool, TaskPlan, EvaluationResult | None]:
        tools = build_openai_tools()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": self._bootstrap_prompt()}
        ]
        edits_since_eval = 0

        while self.iterations < self.settings.agent_max_iterations:
            self.iterations += 1
            self.console.print(f"[cyan]Iteration {self.iterations}[/cyan]")
            self.writer.log(f"=== iteration {self.iterations} ===")

            msg = self.client.chat_with_tools(
                system=LOOP_SYSTEM,
                messages=messages,
                tools=tools,
                temperature=0.2,
                max_tokens=1500,
            )
            tool_calls = msg.get("tool_calls") or []
            messages.append(msg)

            if not tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": "Use tools. If complete, call finish_task.",
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
                self.console.print(f"  tool: {name}")
                self.writer.log(f"tool {name}")
                result = self.runtime.dispatch(name, args)
                if name in {"write_file", "apply_patch"} and result.get("ok"):
                    edits_since_eval += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "name": name,
                        "content": truncate_result(result),
                    }
                )

            should_eval = self.runtime.finish_requested or edits_since_eval >= 3
            if not should_eval:
                continue

            self.console.print("[yellow]Evaluating...[/yellow]")
            self.last_evaluation = evaluate(
                root=self.root,
                context=self.context,
                plan=self.plan,
                settings=self.settings,
                artifacts_dir=self.writer.run_dir / "artifacts",
                skip_browser=self.skip_browser,
                skip_tests=self.skip_tests,
            )
            edits_since_eval = 0
            self.writer.log(f"evaluation: {self.last_evaluation.message}")
            self.console.print(f"  {self.last_evaluation.message}")

            if self.last_evaluation.passed and (
                self.runtime.finish_requested
                or all(st.status == "done" for st in self.plan.subtasks)
            ):
                return True, self.plan, self.last_evaluation

            if not self.last_evaluation.passed:
                feedback = self._failure_feedback(self.last_evaluation)
                try:
                    self.plan = replan(
                        self.client,
                        task=self.task,
                        context=self.context,
                        current=self.plan,
                        failure_feedback=feedback,
                        max_subtasks=self.settings.agent_max_subtasks,
                    )
                    self.runtime.plan = self.plan
                except Exception as exc:  # noqa: BLE001
                    self.writer.log(f"replan skipped: {exc}")
                self.runtime.finish_requested = False
                messages.append(
                    {
                        "role": "user",
                        "content": f"Verification failed. Fix and continue.\n{feedback}",
                    }
                )

        self.last_evaluation = evaluate(
            root=self.root,
            context=self.context,
            plan=self.plan,
            settings=self.settings,
            artifacts_dir=self.writer.run_dir / "artifacts",
            skip_browser=self.skip_browser,
            skip_tests=self.skip_tests,
        )
        ok = bool(self.last_evaluation and self.last_evaluation.passed)
        return ok, self.plan, self.last_evaluation

    def _bootstrap_prompt(self) -> str:
        # Keep prompt small — stack notes only, not full context dump
        return (
            f"TASK: {self.task}\n"
            f"STACK: {self.context.stack_notes}\n"
            f"TOP: {', '.join(self.context.top_level[:20])}\n"
            f"PLAN: {self.plan.model_dump_json()}\n"
            "Start by searching/reading relevant files, then edit."
        )

    def _failure_feedback(self, evaluation: EvaluationResult) -> str:
        parts = [evaluation.message]
        if evaluation.tests and not evaluation.tests.passed:
            parts.append(evaluation.tests.summary[:1500])
        if evaluation.browser and not evaluation.browser.passed:
            parts.append(evaluation.browser.summary[:800])
        return "\n".join(parts)
