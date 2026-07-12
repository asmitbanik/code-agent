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
    help="Multi-agent coding orchestrator: classify -> intake -> RAG -> roles -> PR",
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
