"""Top-level autonomous pipeline with multi-agent RAG orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path

from rich.console import Console

from agent_auto.agents.orchestrator import Orchestrator
from agent_auto.classify import analyze_task, enrich_requirements_from_context, heuristic_plan
from agent_auto.config import Settings, get_settings
from agent_auto.context.scout import clone_repo, scout_repo
from agent_auto.deliver.ship import ship_changes
from agent_auto.intake.env_gate import run_env_gate
from agent_auto.llm.client import create_llm
from agent_auto.models import RunReport, RunStatus
from agent_auto.paths.docs import run_docs_fast_path
from agent_auto.rag.embedder import LocalEmbedder
from agent_auto.rag.indexer import index_repository
from agent_auto.rag.retriever import Retriever
from agent_auto.report.writer import ReportWriter
from agent_auto.tools.shell import run_shell


def run_pipeline(
    *,
    repo_url: str,
    task: str,
    base_branch: str = "main",
    workdir_root: Path | None = None,
    skip_pr: bool = False,
    env_file: Path | None = None,
    assume_yes: bool = False,
    settings: Settings | None = None,
    console: Console | None = None,
) -> RunReport:
    settings = settings or get_settings()
    console = console or Console()
    workdir_root = Path(workdir_root or settings.agent_workdir).resolve()
    workdir_root.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex[:12]
    run_dir = workdir_root / run_id
    repo_dir = run_dir / "repo"
    chroma_dir = run_dir / "chroma"
    writer = ReportWriter(run_dir)

    # Pre-clone heuristic classify (refined after scout)
    requirements = analyze_task(task)
    report = RunReport(
        run_id=run_id,
        task=task,
        repo_url=repo_url,
        base_branch=base_branch,
        workdir=str(run_dir),
        extra={
            "complexity": requirements.complexity,
            "clone_path": str(repo_dir),
            "chroma_path": str(chroma_dir),
        },
    )
    writer.save(report)
    writer.log(f"run_id={run_id} task={task!r} complexity={requirements.complexity}")
    console.print(
        f"[bold]Classify[/bold] {requirements.complexity} "
        f"(confidence={requirements.confidence:.2f}) — {requirements.reason}"
    )

    try:
        console.print(f"[bold]Cloning[/bold] into {repo_dir} ...")
        clone_repo(repo_url, repo_dir, base_branch=base_branch)
        run_shell(repo_dir, f"git checkout {base_branch} || git checkout -B {base_branch}")

        console.print("[bold]Scouting[/bold] (no LLM) ...")
        context = scout_repo(repo_url, repo_dir)
        context.default_branch = base_branch or context.default_branch
        report.context = context
        enrich_requirements_from_context(requirements, context)
        report.extra["requirements"] = {
            "needs_db": requirements.needs_db,
            "needs_auth": requirements.needs_auth,
            "needs_browser": requirements.needs_browser,
            "env_keys": requirements.env_keys_required,
            "dep_commands": requirements.dep_commands,
        }
        writer.save(report)
        console.print(f"  stack: {context.stack_notes}")

        # Env / deps intake — interactive prompts when needed
        if requirements.complexity != "docs":
            console.print("[bold]Intake[/bold] env + dependencies ...")
            run_env_gate(
                root=repo_dir,
                requirements=requirements,
                console=console,
                env_file=env_file,
                assume_yes=assume_yes,
            )
        else:
            console.print("  [dim]docs tier — skipping env/deps gate[/dim]")

        # Docs fast path
        if requirements.complexity == "docs":
            plan = heuristic_plan(task, requirements.to_task_class())
            report.plan = plan
            client = create_llm(settings)
            ok, evaluation = run_docs_fast_path(
                root=repo_dir,
                task=task,
                task_class=requirements.to_task_class(),
                plan=plan,
                client=client,
                console=console,
            )
            report.iterations = 1
            report.last_evaluation = evaluation
            report.plan = plan
            if not ok:
                report.status = RunStatus.FAILED
                report.error = evaluation.message
                writer.finish(report)
                return report
        else:
            # Index + orchestrate
            embedder = LocalEmbedder()
            store = index_repository(
                root=repo_dir,
                chroma_dir=chroma_dir,
                console=console,
                embedder=embedder,
            )
            retriever = Retriever(store, embedder=embedder)
            client = create_llm(settings)
            orch = Orchestrator(
                client=client,
                retriever=retriever,
                root=repo_dir,
                task=task,
                context=context,
                requirements=requirements,
                settings=settings,
                writer=writer,
                console=console,
            )
            ok, plan, evaluation = orch.run()
            report.plan = plan
            report.iterations = orch.iterations
            report.last_evaluation = evaluation
            if not ok:
                report.status = RunStatus.FAILED
                report.error = (
                    evaluation.message
                    if evaluation
                    else "Orchestrator did not approve the result"
                )
                writer.finish(report)
                return report

        console.print("[bold]Shipping[/bold] branch / PR (no LLM) ...")
        delivery = ship_changes(
            root=repo_dir,
            task=task,
            base_branch=base_branch,
            plan=report.plan,
            evaluation=report.last_evaluation,
            github_token=settings.github_auth_token,
            skip_pr=skip_pr,
        )
        report.branch_name = delivery.get("branch_name")
        report.commit_sha = delivery.get("commit_sha")
        report.pr_url = delivery.get("pr_url")
        report.delivery_note = delivery.get("delivery_note")

        if delivery.get("pr_url"):
            report.status = RunStatus.SUCCESS
        elif delivery.get("commit_sha"):
            report.status = RunStatus.DELIVERY_PARTIAL
        else:
            report.status = RunStatus.FAILED
            report.error = delivery.get("error") or "Delivery failed"

        writer.finish(report)
        return report

    except Exception as exc:  # noqa: BLE001
        report.status = RunStatus.FAILED
        report.error = str(exc)
        writer.log(f"FATAL: {exc}")
        writer.finish(report)
        raise
