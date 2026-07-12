"""Run project tests using scouted command."""

from __future__ import annotations

from pathlib import Path

from agent_auto.models import EvaluationPart
from agent_auto.tools.shell import run_shell


def run_tests(
    root: Path,
    test_command: str | None,
    *,
    timeout_sec: int = 600,
    max_output_chars: int = 20_000,
) -> EvaluationPart:
    if not test_command:
        return EvaluationPart(
            name="tests",
            passed=True,
            exit_code=0,
            summary="No test command detected; treated as skipped/pass for delivery gate.",
        )
    result = run_shell(
        root,
        test_command,
        timeout_sec=timeout_sec,
        max_output_chars=max_output_chars,
    )
    out = (result.get("stdout") or "") + "\n" + (result.get("stderr") or "")
    summary = out.strip()[-2000:] or result.get("error") or ""
    return EvaluationPart(
        name="tests",
        passed=bool(result.get("ok")),
        exit_code=result.get("exit_code"),
        summary=summary,
    )
