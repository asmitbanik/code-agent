"""Tester agent — runs tests/browser based on plan verify flags (no LLM)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agent_auto.classify import TaskRequirements
from agent_auto.config import Settings
from agent_auto.models import EvaluationResult, RepoContext, TaskPlan
from agent_auto.verify.evaluator import evaluate


def run_tester(
    *,
    root: Path,
    context: RepoContext,
    plan: TaskPlan,
    requirements: TaskRequirements,
    settings: Settings,
    artifacts_dir: Path,
    console: Console,
) -> EvaluationResult:
    verify = plan.verify or {}
    skip_tests = requirements.skip_tests or not verify.get("run_tests", True)
    skip_browser = (
        requirements.skip_browser
        or settings.agent_skip_browser
        or not verify.get("browser", False)
    )
    # simple tier: skip heavy verification
    if requirements.complexity == "simple":
        skip_tests = True
        skip_browser = True
    if requirements.complexity == "docs":
        skip_tests = True
        skip_browser = True

    console.print(
        f"  [cyan]tester[/cyan] tests={'on' if not skip_tests else 'skip'} "
        f"browser={'on' if not skip_browser else 'skip'}"
    )
    return evaluate(
        root=root,
        context=context,
        plan=plan,
        settings=settings,
        artifacts_dir=artifacts_dir,
        skip_browser=skip_browser,
        skip_tests=skip_tests,
    )
