"""Docs-only fast path: clone + one LLM rewrite + ship. No tool loop."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agent_auto.classify import TaskClass
from agent_auto.llm.client import LLMClient
from agent_auto.models import EvaluationPart, EvaluationResult, TaskPlan


DOCS_SYSTEM = (
    "You rewrite project documentation. Output ONLY the full markdown file content. "
    "No preamble, no code fences. Keep setup/tech facts accurate. "
    "Make it clear, scannable, and friendly for the stated audience."
)


def find_readme(root: Path) -> Path | None:
    for name in ("README.md", "Readme.md", "readme.md", "README.MD"):
        path = root / name
        if path.is_file():
            return path
    return None


def strip_fences(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def run_docs_fast_path(
    *,
    root: Path,
    task: str,
    task_class: TaskClass,
    plan: TaskPlan,
    client: LLMClient,
    console: Console,
) -> tuple[bool, EvaluationResult]:
    target = None
    if task_class.target_files:
        candidate = root / task_class.target_files[0]
        if candidate.is_file():
            target = candidate
    if target is None:
        target = find_readme(root)
    if target is None:
        return False, EvaluationResult(
            passed=False,
            message="No README.md found",
        )

    original = target.read_text(encoding="utf-8", errors="replace")
    # Cap input size to save tokens
    original_for_llm = original if len(original) <= 12_000 else original[:12_000] + "\n\n[truncated]"

    console.print(f"  [cyan]docs fast-path[/cyan] rewriting {target.name} (1 LLM call)")
    rewritten = client.generate_text(
        system=DOCS_SYSTEM,
        user=(
            f"TASK:\n{task}\n\n"
            f"CURRENT {target.name}:\n{original_for_llm}\n"
        ),
        temperature=0.4,
        max_tokens=4096,
    )
    rewritten = strip_fences(rewritten)
    if len(rewritten) < 80:
        return False, EvaluationResult(
            passed=False,
            message="LLM returned an empty/too-short README",
        )

    target.write_text(rewritten + ("\n" if not rewritten.endswith("\n") else ""), encoding="utf-8")
    for st in plan.subtasks:
        st.status = "done"

    return True, EvaluationResult(
        passed=True,
        tests=EvaluationPart(
            name="tests",
            passed=True,
            summary="SKIPPED (docs-only task)",
        ),
        browser=EvaluationPart(
            name="browser",
            passed=True,
            summary="SKIPPED (docs-only task)",
        ),
        message="docs fast-path OK; tests=SKIP; browser=SKIP",
    )
