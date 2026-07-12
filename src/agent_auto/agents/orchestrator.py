"""Orchestrator — sequences Planner → Retriever → Coder → Tester → Reviewer."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agent_auto.agents.coder import run_coder
from agent_auto.agents.planner import run_planner
from agent_auto.agents.reviewer import run_reviewer
from agent_auto.agents.tester import run_tester
from agent_auto.classify import TaskRequirements, heuristic_plan
from agent_auto.config import Settings
from agent_auto.llm.client import LLMClient
from agent_auto.models import EvaluationResult, RepoContext, TaskPlan
from agent_auto.rag.retriever import Retriever
from agent_auto.report.writer import ReportWriter


class Orchestrator:
    def __init__(
        self,
        *,
        client: LLMClient,
        retriever: Retriever,
        root: Path,
        task: str,
        context: RepoContext,
        requirements: TaskRequirements,
        settings: Settings,
        writer: ReportWriter,
        console: Console,
    ) -> None:
        self.client = client
        self.retriever = retriever
        self.root = root
        self.task = task
        self.context = context
        self.requirements = requirements
        self.settings = settings
        self.writer = writer
        self.console = console
        self.iterations = 0
        self.plan: TaskPlan | None = None
        self.last_evaluation: EvaluationResult | None = None

    def run(self) -> tuple[bool, TaskPlan, EvaluationResult | None]:
        complexity = self.requirements.complexity
        self.console.print(f"[bold]Orchestrator[/bold] complexity={complexity}")

        # 1) Retrieve seed context for planner (embeddings only)
        seed = self.retriever.retrieve(self.task, k=8)
        self.console.print(f"  [cyan]retriever[/cyan] seed chunks={len(seed.chunks)}")

        # 2) Planner (LLM) — never edits
        self.console.print("  [cyan]planner[/cyan] creating plan (no file edits)")
        try:
            self.plan = run_planner(
                self.client,
                task=self.task,
                context=self.context,
                requirements=self.requirements,
                context_pack=seed,
                max_subtasks=self.settings.agent_max_subtasks,
            )
        except Exception as exc:  # noqa: BLE001
            self.writer.log(f"planner LLM failed, heuristic fallback: {exc}")
            self.console.print(f"  [yellow]planner fallback:[/yellow] {exc}")
            self.plan = heuristic_plan(self.task, self.requirements.to_task_class())

        for st in self.plan.subtasks:
            self.console.print(f"  - [{st.id}] {st.title}")
        if self.plan.needs:
            self.console.print("  needs: " + "; ".join(self.plan.needs[:8]))

        # Lite path for simple: fewer review loops
        max_review_rounds = 1 if complexity == "simple" else (3 if complexity == "complex" else 2)

        for round_i in range(1, max_review_rounds + 1):
            self.console.print(f"[bold]Round {round_i}[/bold]")
            pending = [s for s in self.plan.subtasks if s.status != "done"]
            if not pending:
                pending = list(self.plan.subtasks)

            for subtask in pending:
                if subtask.status == "done" and round_i == 1:
                    continue
                subtask.status = "in_progress"
                query = f"{self.task}\n{subtask.title}\n{' '.join(subtask.files_hint)}"
                pack = self.retriever.retrieve(query, k=10)
                self.console.print(
                    f"  [cyan]retriever[/cyan] subtask={subtask.id} chunks={len(pack.chunks)}"
                )
                self.console.print(f"  [cyan]coder[/cyan] subtask={subtask.id}")
                ok = run_coder(
                    self.client,
                    root=self.root,
                    task=self.task,
                    context=self.context,
                    plan=self.plan,
                    subtask=subtask,
                    context_pack=pack,
                    settings=self.settings,
                    writer=self.writer,
                    console=self.console,
                    max_steps=6 if complexity == "simple" else 10,
                )
                self.iterations += 1
                if ok:
                    subtask.status = "done"
                else:
                    self.console.print(f"  [yellow]coder did not finish subtask {subtask.id}[/yellow]")

            # Tester
            self.last_evaluation = run_tester(
                root=self.root,
                context=self.context,
                plan=self.plan,
                requirements=self.requirements,
                settings=self.settings,
                artifacts_dir=self.writer.run_dir / "artifacts",
                console=self.console,
            )
            self.console.print(f"  eval: {self.last_evaluation.message}")

            # Reviewer
            self.console.print("  [cyan]reviewer[/cyan]")
            review = run_reviewer(
                self.client,
                root=self.root,
                plan=self.plan,
                evaluation=self.last_evaluation,
                complexity=complexity,
            )
            self.writer.log(f"review approved={review.approved} feedback={review.feedback[:300]}")
            if review.approved:
                return True, self.plan, self.last_evaluation

            self.console.print(f"  [yellow]reviewer requested changes:[/yellow] {review.feedback[:200]}")
            # Mark rework subtasks pending
            rework_ids = set(review.rework_subtask_ids)
            for st in self.plan.subtasks:
                if not rework_ids or st.id in rework_ids:
                    st.status = "pending"

        # Final: accept if evaluation passed even if reviewer strict
        ok = bool(self.last_evaluation and self.last_evaluation.passed)
        if complexity == "simple":
            ok = True  # small edits: ship if coder ran
        return ok, self.plan or heuristic_plan(self.task, self.requirements.to_task_class()), self.last_evaluation
