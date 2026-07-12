"""Branch, commit, push, and open a GitHub PR after green verification."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from agent_auto.models import EvaluationResult, TaskPlan


def _run(
    cmd: list[str],
    cwd: Path,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=merged,
    )


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s or "task")[:max_len]


def create_branch_name(task: str, short_sha: str) -> str:
    return f"agent/{slugify(task)}-{short_sha[:7]}"


def ship_changes(
    *,
    root: Path,
    task: str,
    base_branch: str,
    plan: TaskPlan,
    evaluation: EvaluationResult | None,
    github_token: str,
    skip_pr: bool = False,
) -> dict:
    status = _run(["git", "status", "--porcelain"], root)
    if not (status.stdout or "").strip():
        return {
            "ok": False,
            "error": "No local changes to commit",
            "branch_name": None,
            "commit_sha": None,
            "pr_url": None,
            "delivery_note": "Nothing to ship",
        }

    sha = _run(["git", "rev-parse", "--short", "HEAD"], root).stdout.strip() or "0000000"
    branch = create_branch_name(task, sha)

    # Ensure we are on a new branch from current HEAD (already based on base)
    checkout = _run(["git", "checkout", "-B", branch], root)
    if checkout.returncode != 0:
        return {
            "ok": False,
            "error": checkout.stderr or "Failed to create branch",
            "branch_name": branch,
            "commit_sha": None,
            "pr_url": None,
            "delivery_note": None,
        }

    _run(["git", "add", "-A"], root)
    # Ensure identity for unattended commits
    if not _run(["git", "config", "user.email"], root).stdout.strip():
        _run(["git", "config", "user.email", "agent-auto@localhost"], root)
        _run(["git", "config", "user.name", "agent-auto"], root)
    message = f"agent: {task.strip()[:72]}"
    body_lines = [
        f"Goal: {plan.goal}",
        "",
        "Subtasks:",
        *[f"- [{st.status}] {st.title}" for st in plan.subtasks],
        "",
        f"Verification: {evaluation.message if evaluation else 'n/a'}",
    ]
    commit = _run(
        ["git", "commit", "-m", message, "-m", "\n".join(body_lines)],
        root,
    )
    if commit.returncode != 0:
        return {
            "ok": False,
            "error": commit.stderr or commit.stdout or "Commit failed",
            "branch_name": branch,
            "commit_sha": None,
            "pr_url": None,
            "delivery_note": None,
        }

    commit_sha = _run(["git", "rev-parse", "HEAD"], root).stdout.strip()

    if skip_pr:
        return {
            "ok": True,
            "branch_name": branch,
            "commit_sha": commit_sha,
            "pr_url": None,
            "delivery_note": "Skipped push/PR (--skip-pr)",
        }

    if not github_token:
        return {
            "ok": True,
            "branch_name": branch,
            "commit_sha": commit_sha,
            "pr_url": None,
            "delivery_note": "Local commit only - set GH_TOKEN to push and open a PR",
        }

    # Configure credential helper via env for this push
    env_push = _run(
        ["git", "push", "-u", "origin", branch],
        root,
        timeout=180,
    )
    # Retry with tokenized URL if plain push fails
    if env_push.returncode != 0:
        remote = _run(["git", "remote", "get-url", "origin"], root).stdout.strip()
        if remote.startswith("https://") and "github.com" in remote:
            authed = remote.replace(
                "https://",
                f"https://x-access-token:{github_token}@",
                1,
            )
            env_push = _run(["git", "push", "-u", authed, branch], root, timeout=180)

    if env_push.returncode != 0:
        return {
            "ok": True,
            "branch_name": branch,
            "commit_sha": commit_sha,
            "pr_url": None,
            "delivery_note": f"Push failed: {(env_push.stderr or env_push.stdout)[:500]}",
        }

    pr_body = "\n".join(
        [
            "## Summary",
            f"- {plan.goal}",
            "",
            "## Subtasks",
            *[f"- {st.title} ({st.status})" for st in plan.subtasks],
            "",
            "## Verification",
            f"- {evaluation.message if evaluation else 'n/a'}",
            "",
            "_Opened automatically by agent-auto._",
        ]
    )
    pr = _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            message,
            "--body",
            pr_body,
        ],
        root,
        timeout=120,
        env={"GH_TOKEN": github_token, "GITHUB_TOKEN": github_token},
    )
    if pr.returncode != 0:
        return {
            "ok": True,
            "branch_name": branch,
            "commit_sha": commit_sha,
            "pr_url": None,
            "delivery_note": f"Push succeeded but PR failed: {(pr.stderr or pr.stdout)[:500]}",
        }

    pr_url = (pr.stdout or "").strip().splitlines()[-1] if pr.stdout else None
    return {
        "ok": True,
        "branch_name": branch,
        "commit_sha": commit_sha,
        "pr_url": pr_url,
        "delivery_note": "PR created",
    }
