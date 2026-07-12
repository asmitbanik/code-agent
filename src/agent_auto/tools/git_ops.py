"""Read-only / local git helpers used during the act loop."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git_status(root: Path) -> dict:
    r = _git(root, "status", "--porcelain", "-b")
    return {
        "ok": r.returncode == 0,
        "status": (r.stdout or "").strip(),
        "stderr": (r.stderr or "").strip(),
    }


def git_diff(root: Path, staged: bool = False) -> dict:
    args = ["diff", "--stat"] if not staged else ["diff", "--cached", "--stat"]
    r = _git(root, *args)
    full = _git(root, "diff", *(["--cached"] if staged else []))
    diff_text = (full.stdout or "")[-15_000:]
    return {
        "ok": r.returncode == 0,
        "stat": (r.stdout or "").strip(),
        "diff": diff_text,
        "stderr": (r.stderr or "").strip(),
    }


def git_current_sha(root: Path) -> str:
    r = _git(root, "rev-parse", "HEAD")
    return (r.stdout or "").strip()
