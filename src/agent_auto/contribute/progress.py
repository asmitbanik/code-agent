"""Progress gate: claim issue only after >50% solved."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_auto.models import EvaluationResult, TaskPlan


def _meaningful_diff(root: Path) -> bool:
    r = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    stat = (r.stdout or "").strip()
    if not stat:
        # staged?
        r2 = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        stat = (r2.stdout or "").strip()
    if not stat:
        return False
    # Ignore pure whitespace-ish tiny diffs
    return len(stat) > 10


def progress_ratio(
    *,
    root: Path,
    plan: TaskPlan | None,
    evaluation: EvaluationResult | None,
    ux_passed: bool,
) -> float:
    scores: list[float] = []
    if plan and plan.subtasks:
        done = sum(1 for s in plan.subtasks if s.status == "done")
        scores.append(done / max(1, len(plan.subtasks)))
    else:
        scores.append(0.0)

    scores.append(1.0 if _meaningful_diff(root) else 0.0)

    if ux_passed:
        scores.append(1.0)
    elif evaluation and evaluation.passed:
        scores.append(0.7)
    else:
        scores.append(0.0)

    return sum(scores) / len(scores)


def should_claim(*, root: Path, plan: TaskPlan | None, evaluation: EvaluationResult | None, ux_passed: bool) -> bool:
    return progress_ratio(root=root, plan=plan, evaluation=evaluation, ux_passed=ux_passed) >= 0.5
