"""CI watch + fix loop with PR comments."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from rich.console import Console

from agent_auto.agents.orchestrator import Orchestrator
from agent_auto.classify import analyze_task, enrich_requirements_from_context
from agent_auto.config import Settings
from agent_auto.context.scout import scout_repo
from agent_auto.llm.client import LLMClient
from agent_auto.rag.retriever import Retriever
from agent_auto.report.writer import ReportWriter


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def comment_pr(repo: str, pr_number: int, body: str) -> None:
    _run(["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body", body])


def get_pr_number_from_url(pr_url: str) -> int | None:
    # https://github.com/owner/repo/pull/12
    try:
        return int(pr_url.rstrip("/").split("/")[-1])
    except ValueError:
        return None


def wait_for_checks(
    *,
    repo: str,
    pr_number: int,
    console: Console,
    timeout_sec: int = 900,
) -> tuple[str, str]:
    """Return (status, detail) where status in pass|fail|pending|unknown."""
    deadline = time.time() + timeout_sec
    last = "pending"
    detail = ""
    while time.time() < deadline:
        r = _run(
            ["gh", "pr", "checks", str(pr_number), "--repo", repo, "--json", "name,state,bucket"],
            timeout=60,
        )
        if r.returncode != 0:
            # Some repos have no checks
            if "no checks" in (r.stderr or "").lower() or "no checks" in (r.stdout or "").lower():
                return "pass", "no CI checks configured"
            time.sleep(15)
            continue
        try:
            checks = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            time.sleep(15)
            continue
        if not checks:
            return "pass", "no CI checks configured"
        states = [str(c.get("bucket") or c.get("state") or "").lower() for c in checks]
        detail = ", ".join(
            f"{c.get('name')}:{c.get('bucket') or c.get('state')}" for c in checks[:12]
        )
        if any(s in {"fail", "failure", "failed"} for s in states):
            return "fail", detail
        if all(s in {"pass", "success", "skipping", "neutral"} for s in states):
            return "pass", detail
        last = "pending"
        console.print(f"  CI pending: {detail[:160]}")
        time.sleep(20)
    return last, detail or "CI wait timed out"


def fetch_failed_logs(repo: str, pr_number: int, max_chars: int = 8000) -> str:
    # Try latest failed run on the PR branch
    r = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--branch",
            _pr_head_branch(repo, pr_number) or "",
            "--status",
            "failure",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ]
    )
    try:
        runs = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        runs = []
    if not runs:
        return "Unable to fetch failed workflow logs."
    run_id = str(runs[0].get("databaseId"))
    logs = _run(["gh", "run", "view", run_id, "--repo", repo, "--log-failed"], timeout=180)
    text = (logs.stdout or logs.stderr or "")[-max_chars:]
    return text or "Empty failed logs."


def _pr_head_branch(repo: str, pr_number: int) -> str | None:
    r = _run(
        ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "headRefName"]
    )
    try:
        data = json.loads(r.stdout or "{}")
        return data.get("headRefName")
    except json.JSONDecodeError:
        return None


def push_branch(root: Path, branch: str, github_token: str) -> bool:
    r = _run(["git", "push", "origin", branch], cwd=root, timeout=180)
    if r.returncode == 0:
        return True
    remote = _run(["git", "remote", "get-url", "origin"], cwd=root).stdout.strip()
    if remote.startswith("https://") and github_token:
        authed = remote.replace("https://", f"https://x-access-token:{github_token}@", 1)
        r2 = _run(["git", "push", authed, branch], cwd=root, timeout=180)
        return r2.returncode == 0
    return False


def run_ci_fix_loop(
    *,
    root: Path,
    repo: str,
    pr_url: str,
    branch: str,
    client: LLMClient,
    retriever: Retriever,
    settings: Settings,
    writer: ReportWriter,
    console: Console,
    github_token: str,
    max_retries: int = 3,
) -> tuple[bool, str]:
    pr_number = get_pr_number_from_url(pr_url)
    if not pr_number:
        return False, "Could not parse PR number"

    for attempt in range(1, max_retries + 1):
        console.print(f"  [cyan]ci_loop[/cyan] attempt {attempt}/{max_retries}")
        status, detail = wait_for_checks(repo=repo, pr_number=pr_number, console=console)
        if status == "pass":
            comment_pr(repo, pr_number, "All CI checks passed.")
            return True, detail
        if status != "fail":
            comment_pr(repo, pr_number, f"CI still pending/timeout: {detail}")
            return False, detail

        logs = fetch_failed_logs(repo, pr_number)
        (writer.run_dir / "artifacts").mkdir(exist_ok=True)
        log_path = writer.run_dir / "artifacts" / f"ci_fail_{attempt}.log"
        log_path.write_text(logs, encoding="utf-8")
        comment_pr(
            repo,
            pr_number,
            f"CI failed (attempt {attempt}/{max_retries}).\n\n"
            f"Checks: `{detail}`\n\n"
            "I'm iterating on a fix and will push follow-up commits.",
        )

        context = scout_repo(repo, root)
        requirements = analyze_task(f"Fix CI failures on PR\n{logs[:2000]}")
        enrich_requirements_from_context(requirements, context)
        orch = Orchestrator(
            client=client,
            retriever=retriever,
            root=root,
            task=(
                "Fix the failing CI checks for this PR. "
                "Do not expand scope beyond making CI green.\n\n"
                f"FAILED CHECKS:\n{detail}\n\nLOGS:\n{logs[:6000]}"
            ),
            context=context,
            requirements=requirements,
            settings=settings,
            writer=writer,
            console=console,
        )
        ok, _plan, _ev = orch.run()
        if not ok:
            console.print("  [yellow]CI fix orchestrator did not fully succeed[/yellow]")

        # Commit any fixes
        st = _run(["git", "status", "--porcelain"], cwd=root)
        if (st.stdout or "").strip():
            _run(["git", "add", "-A"], cwd=root)
            if not _run(["git", "config", "user.email"], cwd=root).stdout.strip():
                _run(["git", "config", "user.email", "agent-auto@localhost"], cwd=root)
                _run(["git", "config", "user.name", "agent-auto"], cwd=root)
            _run(
                ["git", "commit", "-m", f"fix: address CI failures (attempt {attempt})"],
                cwd=root,
            )
            if not push_branch(root, branch, github_token):
                return False, "Failed to push CI fix commits"
        else:
            comment_pr(repo, pr_number, "No local changes produced for CI fix; stopping retries.")
            return False, detail

    comment_pr(
        repo,
        pr_number,
        f"Reached max CI retries ({max_retries}). Leaving PR open for human help.",
    )
    return False, "max CI retries exhausted"
