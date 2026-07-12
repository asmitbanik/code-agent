"""Tool registry: OpenAI/Groq function schemas + dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent_auto.config import Settings
from agent_auto.models import RepoContext, TaskPlan
from agent_auto.tools import fs, git_ops, search, shell
from agent_auto.tools.browser import browser_smoke
from agent_auto.tools.tests_runner import run_tests


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def build_openai_tools() -> list[dict[str, Any]]:
    return [
        _fn("list_dir", "List files under a relative path.", {"path": {"type": "string"}}),
        _fn(
            "read_file",
            "Read a text file.",
            {"path": {"type": "string"}},
            ["path"],
        ),
        _fn(
            "write_file",
            "Create/overwrite a text file.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        ),
        _fn(
            "apply_patch",
            "Replace one exact occurrence of old_text with new_text.",
            {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            ["path", "old_text", "new_text"],
        ),
        _fn(
            "search_code",
            "Regex search the codebase.",
            {"pattern": {"type": "string"}, "glob": {"type": "string"}},
            ["pattern"],
        ),
        _fn(
            "run_shell",
            "Run a shell command in the repo.",
            {"command": {"type": "string"}},
            ["command"],
        ),
        _fn("run_tests", "Run detected project tests.", {}),
        _fn(
            "browser_smoke",
            "Browser smoke checks (web apps).",
            {
                "checks": {"type": "array", "items": {"type": "string"}},
                "base_url": {"type": "string"},
            },
        ),
        _fn("git_status", "Show git status.", {}),
        _fn("git_diff", "Show git diff.", {"staged": {"type": "boolean"}}),
        _fn(
            "mark_subtask_done",
            "Mark a subtask done.",
            {"subtask_id": {"type": "string"}, "note": {"type": "string"}},
            ["subtask_id"],
        ),
        _fn(
            "finish_task",
            "Declare task complete and request final verification.",
            {"summary": {"type": "string"}},
            ["summary"],
        ),
    ]


class ToolRuntime:
    def __init__(
        self,
        *,
        root: Path,
        context: RepoContext,
        plan: TaskPlan,
        settings: Settings,
        artifacts_dir: Path,
        skip_browser: bool = False,
        skip_tests: bool = False,
    ) -> None:
        self.root = root
        self.context = context
        self.plan = plan
        self.settings = settings
        self.artifacts_dir = artifacts_dir
        self.skip_browser = skip_browser
        self.skip_tests = skip_tests
        self.edited = False
        self.finish_requested = False
        self.finish_summary = ""
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "list_dir": self._list_dir,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "apply_patch": self._apply_patch,
            "search_code": self._search_code,
            "run_shell": self._run_shell,
            "run_tests": self._run_tests,
            "browser_smoke": self._browser_smoke,
            "git_status": self._git_status,
            "git_diff": self._git_diff,
            "mark_subtask_done": self._mark_subtask_done,
            "finish_task": self._finish_task,
        }

    def dispatch(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if not handler:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        try:
            return handler(args or {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _list_dir(self, args: dict[str, Any]) -> dict[str, Any]:
        return fs.list_dir(self.root, args.get("path") or ".")

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return fs.read_file(self.root, str(args.get("path") or ""))

    def _write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        self.edited = True
        return fs.write_file(self.root, str(args["path"]), str(args.get("content") or ""))

    def _apply_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        result = fs.apply_patch(
            self.root,
            str(args["path"]),
            str(args.get("old_text") or ""),
            str(args.get("new_text") or ""),
        )
        if result.get("ok"):
            self.edited = True
        return result

    def _search_code(self, args: dict[str, Any]) -> dict[str, Any]:
        return search.search_code(
            self.root,
            str(args.get("pattern") or ""),
            glob=args.get("glob"),
        )

    def _run_shell(self, args: dict[str, Any]) -> dict[str, Any]:
        return shell.run_shell(
            self.root,
            str(args.get("command") or ""),
            timeout_sec=self.settings.shell_timeout_sec,
            max_output_chars=self.settings.max_tool_output_chars,
        )

    def _run_tests(self, _args: dict[str, Any]) -> dict[str, Any]:
        if self.skip_tests:
            return {"ok": True, "summary": "SKIPPED"}
        part = run_tests(
            self.root,
            self.context.test_command,
            timeout_sec=self.settings.shell_timeout_sec,
            max_output_chars=self.settings.max_tool_output_chars,
        )
        return part.model_dump()

    def _browser_smoke(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.skip_browser or self.settings.agent_skip_browser:
            return {"ok": True, "summary": "SKIPPED"}
        checks = args.get("checks") or self.plan.browser_checks or self.plan.success_criteria
        part = browser_smoke(
            self.root,
            start_command=self.context.start_command,
            checks=list(checks),
            artifacts_dir=self.artifacts_dir,
            base_url=args.get("base_url"),
        )
        return part.model_dump()

    def _git_status(self, _args: dict[str, Any]) -> dict[str, Any]:
        return git_ops.git_status(self.root)

    def _git_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        return git_ops.git_diff(self.root, staged=bool(args.get("staged")))

    def _mark_subtask_done(self, args: dict[str, Any]) -> dict[str, Any]:
        sid = str(args.get("subtask_id") or "")
        for st in self.plan.subtasks:
            if st.id == sid:
                st.status = "done"
                return {"ok": True, "subtask_id": sid, "note": args.get("note")}
        return {"ok": False, "error": f"Unknown subtask_id: {sid}"}

    def _finish_task(self, args: dict[str, Any]) -> dict[str, Any]:
        self.finish_requested = True
        self.finish_summary = str(args.get("summary") or "")
        return {"ok": True, "finish_requested": True, "summary": self.finish_summary}


def truncate_result(result: dict[str, Any], limit: int = 6_000) -> str:
    raw = json.dumps(result, default=str)
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "...(truncated)"
