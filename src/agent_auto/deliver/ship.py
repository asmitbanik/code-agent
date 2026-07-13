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
        encoding="utf-8",
        errors="replace",
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
    branch_name: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    pr_repo: str | None = None,
    head: str | None = None,
    create_branch: bool = True,
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
    branch = branch_name or create_branch_name(task, sha)

    if create_branch:
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
    if not _run(["git", "config", "user.email"], root).stdout.strip():
        _run(["git", "config", "user.email", "agent-auto@localhost"], root)
        _run(["git", "config", "user.name", "agent-auto"], root)

    message = pr_title or f"agent: {task.strip()[:72]}"
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
        # maybe nothing new staged beyond previous commit attempt
        if "nothing to commit" not in ((commit.stdout or "") + (commit.stderr or "")).lower():
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

    env_push = _run(["git", "push", "-u", "origin", branch], root, timeout=180)
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

    body = pr_body or "\n".join(
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

    pr_cmd = [
        "gh",
        "pr",
        "create",
        "--base",
        base_branch,
        "--title",
        message,
        "--body",
        body,
    ]
    if pr_repo:
        pr_cmd.extend(["--repo", pr_repo])
    if head:
        pr_cmd.extend(["--head", head])
    else:
        pr_cmd.extend(["--head", branch])

    pr = _run(
        pr_cmd,
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
