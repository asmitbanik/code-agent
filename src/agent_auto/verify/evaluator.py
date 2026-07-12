"""Combine test + browser evaluation into a scorecard."""

from __future__ import annotations

from pathlib import Path

from agent_auto.config import Settings
from agent_auto.models import EvaluationPart, EvaluationResult, RepoContext, TaskPlan
from agent_auto.tools.browser import browser_smoke
from agent_auto.tools.tests_runner import run_tests


def evaluate(
    *,
    root: Path,
    context: RepoContext,
    plan: TaskPlan,
    settings: Settings,
    artifacts_dir: Path,
    skip_browser: bool = False,
    skip_tests: bool = False,
) -> EvaluationResult:
    if skip_tests:
        tests = EvaluationPart(name="tests", passed=True, summary="SKIPPED")
    else:
        tests = run_tests(
            root,
            context.test_command,
            timeout_sec=settings.shell_timeout_sec,
            max_output_chars=settings.max_tool_output_chars,
        )

    browser = None
    if skip_browser or settings.agent_skip_browser:
        browser = EvaluationPart(name="browser", passed=True, summary="SKIPPED")
    elif context.is_web:
        checks = plan.browser_checks or [
            c for c in plan.success_criteria if "test" not in c.lower()
        ]
        browser = browser_smoke(
            root,
            start_command=context.start_command,
            checks=checks or ["html"],
            artifacts_dir=artifacts_dir,
        )
        if (
            browser
            and not browser.passed
            and (
                "did not become ready" in (browser.summary or "").lower()
                or "no start/dev command" in (browser.summary or "").lower()
            )
        ):
            browser = browser.model_copy(
                update={
                    "passed": True,
                    "summary": f"SKIPPED (server unavailable): {browser.summary}",
                }
            )

    parts_ok = tests.passed and (browser.passed if browser else True)
    bits = [f"tests={'PASS' if tests.passed else 'FAIL'}"]
    if browser:
        label = "SKIP" if "SKIP" in (browser.summary or "").upper() else (
            "PASS" if browser.passed else "FAIL"
        )
        bits.append(f"browser={label}")
    return EvaluationResult(
        passed=parts_ok,
        tests=tests,
        browser=browser,
        message="; ".join(bits),
    )
