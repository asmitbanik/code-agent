"""Autonomous contribute runner: issues -> solve -> UX -> PR -> CI."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from rich.console import Console

from agent_auto.agents.orchestrator import Orchestrator
from agent_auto.classify import analyze_task, enrich_requirements_from_context, heuristic_plan
from agent_auto.config import Settings, get_settings
from agent_auto.context.scout import scout_repo
from agent_auto.contribute.claim import claim_issue
from agent_auto.contribute.ci_loop import run_ci_fix_loop
from agent_auto.contribute.eligibility import filter_eligible
from agent_auto.contribute.forking import checkout_issue_branch, ensure_workspace
from agent_auto.contribute.issues import (
    enrich_linked_prs,
    fetch_open_issues,
    gh_whoami,
    issue_to_task,
    parse_repo_slug,
)
from agent_auto.contribute.pr_body import build_pr_body, build_pr_title, infer_change_kind
from agent_auto.contribute.progress import should_claim
from agent_auto.contribute.rank import rank_issues
from agent_auto.contribute.runtime_profile import detect_runtime_profile
from agent_auto.contribute.state import ContributeState
from agent_auto.contribute.ux_verify import run_ux_verify
from agent_auto.deliver.ship import ship_changes
from agent_auto.intake.env_gate import run_env_gate
from agent_auto.llm.client import create_llm
from agent_auto.paths.docs import run_docs_fast_path
from agent_auto.rag.embedder import LocalEmbedder
from agent_auto.rag.indexer import index_repository
from agent_auto.rag.retriever import Retriever
from agent_auto.report.writer import ReportWriter


def run_contribute(
    *,
    repo: str,
    limit: int = 10,
    labels: list[str] | None = None,
    base_branch: str | None = None,
    workdir_root: Path | None = None,
    env_file: Path | None = None,
    assume_yes: bool = False,
    max_ci_retries: int = 3,
    allow_unverified: bool = False,
    skip_pr: bool = False,
    settings: Settings | None = None,
    console: Console | None = None,
) -> dict:
    settings = settings or get_settings()
    console = console or Console()
    owner, name = parse_repo_slug(repo)
    me = gh_whoami()
    if not me:
        raise RuntimeError("Could not determine GitHub user (gh auth login?)")

    workdir_root = Path(workdir_root or settings.agent_workdir).resolve()
    contrib_root = workdir_root / "contribute" / f"{owner}__{name}"
    contrib_root.mkdir(parents=True, exist_ok=True)
    state = ContributeState(contrib_root / "state.json")
    profile = detect_runtime_profile()
    console.print(f"[bold]Runtime[/bold] {profile.os_name} ram={profile.ram_gb}G docker={profile.has_docker}")
    for note in profile.notes:
        console.print(f"  [dim]{note}[/dim]")

    console.print(f"[bold]Fetching[/bold] open issues from {owner}/{name} ...")
    issues = fetch_open_issues(owner, name, limit=limit, labels=labels)
    enrich_linked_prs(owner, name, issues)
    eligible = filter_eligible(issues, me=me)
    ranked = rank_issues(eligible)
    selected = [i for i in ranked if not state.already_done(i.number)][:limit]

    console.print(f"  open={len(issues)} eligible={len(eligible)} selected={len(selected)}")
    for issue in selected:
        console.print(f"  #{issue.number} [{issue.complexity}] {issue.title[:70]}")

    ws = ensure_workspace(
        owner=owner,
        name=name,
        dest=contrib_root / "repo",
        me=me,
        base_branch=base_branch,
    )
    console.print(
        f"[bold]Workspace[/bold] push={ws.has_push} head={ws.head_repo} "
        f"branch_base={ws.default_branch} path={ws.root}"
    )

    results: list[dict] = []
    client = create_llm(settings)
    embedder = LocalEmbedder()

    for issue in selected:
        console.print(f"\n[bold cyan]═══ Issue #{issue.number} ({issue.complexity}) ═══[/bold cyan]")
        state.set_issue(issue.number, status="in_progress", title=issue.title)
        run_id = uuid.uuid4().hex[:10]
        run_dir = contrib_root / f"issue-{issue.number}-{run_id}"
        writer = ReportWriter(run_dir)

        try:
            branch = checkout_issue_branch(ws, issue.number, issue.title)
            task = issue_to_task(issue)
            requirements = analyze_task(task)
            context = scout_repo(f"https://github.com/{owner}/{name}.git", ws.root)
            enrich_requirements_from_context(requirements, context)

            if requirements.complexity != "docs":
                run_env_gate(
                    root=ws.root,
                    requirements=requirements,
                    console=console,
                    env_file=env_file,
                    assume_yes=assume_yes,
                )

            plan = None
            evaluation = None
            if requirements.complexity == "docs":
                plan = heuristic_plan(task, requirements.to_task_class())
                ok, evaluation = run_docs_fast_path(
                    root=ws.root,
                    task=task,
                    task_class=requirements.to_task_class(),
                    plan=plan,
                    client=client,
                    console=console,
                )
                if not ok:
                    state.set_issue(issue.number, status="failed", error=evaluation.message)
                    results.append({"issue": issue.number, "status": "failed", "error": evaluation.message})
                    continue
            else:
                store = index_repository(
                    root=ws.root,
                    chroma_dir=contrib_root / "chroma",
                    console=console,
                    embedder=embedder,
                )
                retriever = Retriever(store, embedder=embedder)
                orch = Orchestrator(
                    client=client,
                    retriever=retriever,
                    root=ws.root,
                    task=task,
                    context=context,
                    requirements=requirements,
                    settings=settings,
                    writer=writer,
                    console=console,
                )
                ok, plan, evaluation = orch.run()
                if not ok:
                    state.set_issue(
                        issue.number,
                        status="failed",
                        error=(evaluation.message if evaluation else "orchestrator failed"),
                    )
                    results.append({"issue": issue.number, "status": "failed"})
                    continue

            # UX gate
            ux = run_ux_verify(
                root=ws.root,
                issue=issue,
                context=context,
                profile=profile,
                artifacts_dir=run_dir / "artifacts" / "ux",
                console=console,
                client=client,
                allow_unverified=allow_unverified or requirements.complexity == "docs",
            )
            console.print(f"  UX: {ux.summary}")
            if not ux.passed:
                state.set_issue(issue.number, status="failed", error=f"UX failed: {ux.summary}")
                results.append({"issue": issue.number, "status": "ux_failed", "detail": ux.summary})
                continue

            # Progress gate -> claim
            if should_claim(
                root=ws.root,
                plan=plan,
                evaluation=evaluation,
                ux_passed=ux.passed,
            ):
                claim_issue(ws.upstream_repo, issue.number)
                console.print("  claimed issue via comment")

            kind = infer_change_kind(issue, plan)
            title = build_pr_title(issue, kind)
            body = build_pr_body(
                issue=issue,
                plan=plan,
                evaluation=evaluation,
                ux_summary=ux.summary,
                change_kind=kind,
            )

            head = branch if ws.has_push else f"{ws.fork_owner}:{branch}"
            delivery = ship_changes(
                root=ws.root,
                task=task,
                base_branch=ws.default_branch,
                plan=plan,
                evaluation=evaluation,
                github_token=settings.github_auth_token,
                skip_pr=skip_pr,
                branch_name=branch,
                pr_title=title,
                pr_body=body,
                pr_repo=ws.upstream_repo,
                head=head,
                create_branch=False,
            )
            pr_url = delivery.get("pr_url")
            state.set_issue(
                issue.number,
                status="pr_opened" if pr_url else "delivery_partial",
                pr_url=pr_url,
                branch=branch,
                delivery=delivery.get("delivery_note"),
            )

            if pr_url and not skip_pr:
                # Ensure index exists for CI fix loop
                store = index_repository(
                    root=ws.root,
                    chroma_dir=contrib_root / "chroma",
                    console=console,
                    embedder=embedder,
                )
                retriever = Retriever(store, embedder=embedder)
                ci_ok, ci_detail = run_ci_fix_loop(
                    root=ws.root,
                    repo=ws.upstream_repo,
                    pr_url=pr_url,
                    branch=branch,
                    client=client,
                    retriever=retriever,
                    settings=settings,
                    writer=writer,
                    console=console,
                    github_token=settings.github_auth_token,
                    max_retries=max_ci_retries,
                )
                state.set_issue(
                    issue.number,
                    status="ci_passed" if ci_ok else "pr_opened",
                    ci=ci_detail,
                )
                results.append(
                    {
                        "issue": issue.number,
                        "status": "ci_passed" if ci_ok else "pr_opened",
                        "pr_url": pr_url,
                    }
                )
            else:
                results.append(
                    {
                        "issue": issue.number,
                        "status": delivery.get("delivery_note") or "no_pr",
                        "pr_url": pr_url,
                    }
                )

            console.print(f"  PR: {pr_url or delivery.get('delivery_note')}")
            time.sleep(2)

        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]Issue #{issue.number} failed:[/red] {exc}")
            state.set_issue(issue.number, status="failed", error=str(exc))
            results.append({"issue": issue.number, "status": "error", "error": str(exc)})

    return {
        "repo": f"{owner}/{name}",
        "selected": len(selected),
        "results": results,
        "state_path": str(state.path),
    }
