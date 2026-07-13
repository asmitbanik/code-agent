"""CLI entrypoint — runs entirely from the terminal."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from agent_auto import __version__
from agent_auto.config import get_settings

app = typer.Typer(
    name="agent",
    help="Multi-agent OSS orchestrator: run tasks or contribute to issues",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """Autonomous multi-agent coding orchestrator."""


@app.command("run")
def run_cmd(
    repo: str = typer.Option(..., "--repo", "-r", help="Git clone URL"),
    task: str = typer.Option(..., "--task", "-t", help="Natural-language coding task"),
    base_branch: str = typer.Option(
        "main",
        "--base-branch",
        "-b",
        help="Base branch to branch from for the PR",
    ),
    workdir: Optional[Path] = typer.Option(
        None,
        "--workdir",
        "-w",
        help="Directory for run workspaces (default: AGENT_WORKDIR or ./runs)",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Path to env file used to fill target repo .env from .env.example",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts for dependency installs",
    ),
    skip_pr: bool = typer.Option(
        False,
        "--skip-pr",
        help="Commit locally but do not push or open a PR",
    ),
) -> None:
    """Clone a repo, orchestrate agents, verify, and open a PR."""
    from agent_auto.pipeline import run_pipeline

    settings = get_settings()
    root = workdir or settings.agent_workdir
    try:
        report = run_pipeline(
            repo_url=repo,
            task=task,
            base_branch=base_branch,
            workdir_root=Path(root),
            skip_pr=skip_pr,
            env_file=Path(env_file) if env_file else None,
            assume_yes=yes,
            settings=settings,
            console=console,
        )
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        console.print(f"[red]Fatal:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if report.status.value in {"success", "delivery_partial"}:
        console.print(
            Panel.fit(
                f"[green]Done[/green] - {report.status.value}\n"
                f"Branch: {report.branch_name or 'n/a'}\n"
                f"PR: {report.pr_url or report.delivery_note or 'n/a'}\n"
                f"Report: {report.workdir}/report.json",
                title="agent-auto",
            )
        )
        raise typer.Exit(code=0 if report.status.value == "success" else 2)

    console.print(f"[red]Failed:[/red] {report.error or 'see report.json'}")
    raise typer.Exit(code=1)


@app.command("contribute")
def contribute_cmd(
    repo: str = typer.Option(
        ...,
        "--repo",
        "-r",
        help="GitHub repo as owner/name or URL",
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="Max open issues to take this run"),
    labels: Optional[str] = typer.Option(
        None,
        "--labels",
        help="Comma-separated label filter (e.g. 'good first issue,bug')",
    ),
    base_branch: Optional[str] = typer.Option(
        None,
        "--base-branch",
        "-b",
        help="Override default branch",
    ),
    workdir: Optional[Path] = typer.Option(
        None,
        "--workdir",
        "-w",
        help="Directory for contribute workspaces",
    ),
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Env file to fill target .env.example keys",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip install confirmations"),
    max_ci_retries: int = typer.Option(3, "--max-ci-retries", help="CI fix loop attempts"),
    allow_unverified: bool = typer.Option(
        False,
        "--allow-unverified",
        help="Allow PR even if UX/API smoke cannot run",
    ),
    skip_pr: bool = typer.Option(False, "--skip-pr", help="Solve locally without opening PRs"),
) -> None:
    """Autonomously pick open issues (easiest first), solve, PR, and fix CI."""
    from agent_auto.contribute.runner import run_contribute

    settings = get_settings()
    label_list = [x.strip() for x in labels.split(",")] if labels else None
    try:
        summary = run_contribute(
            repo=repo,
            limit=limit,
            labels=label_list,
            base_branch=base_branch,
            workdir_root=Path(workdir) if workdir else settings.agent_workdir,
            env_file=Path(env_file) if env_file else None,
            assume_yes=yes,
            max_ci_retries=max_ci_retries,
            allow_unverified=allow_unverified,
            skip_pr=skip_pr,
            settings=settings,
            console=console,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Fatal:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    lines = [
        f"Repo: {summary.get('repo')}",
        f"Selected: {summary.get('selected')}",
        f"State: {summary.get('state_path')}",
    ]
    for item in summary.get("results") or []:
        lines.append(
            f"  #{item.get('issue')}: {item.get('status')} {item.get('pr_url') or ''}".rstrip()
        )
    console.print(Panel.fit("\n".join(lines), title="contribute"))
    failed = [
        r
        for r in (summary.get("results") or [])
        if str(r.get("status") or "") in {"failed", "error", "ux_failed"}
    ]
    raise typer.Exit(code=1 if failed else 0)


@app.command("doctor")
def doctor_cmd() -> None:
    """Check LLM keys, git, gh, Playwright, and RAG deps."""
    from agent_auto.doctor import run_doctor

    ok = run_doctor(console)
    raise typer.Exit(code=0 if ok else 1)


@app.command("version")
def version_cmd() -> None:
    """Print version."""
    console.print(__version__)


if __name__ == "__main__":
    app()
    sys.exit(0)
