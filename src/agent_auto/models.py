"""Shared data models for plans, context, and run reports."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Subtask(BaseModel):
    id: str
    title: str
    done_when: str
    status: str = "pending"  # pending | in_progress | done | skipped
    files_hint: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    goal: str
    success_criteria: list[str] = Field(default_factory=list)
    subtasks: list[Subtask] = Field(default_factory=list)
    browser_checks: list[str] = Field(
        default_factory=list,
        description="Text or CSS selectors to assert in browser smoke when web app.",
    )
    needs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    verify: dict[str, bool] = Field(default_factory=dict)


class RepoContext(BaseModel):
    repo_url: str
    workdir: str
    current_branch: str = ""
    default_branch: str = "main"
    remotes: list[str] = Field(default_factory=list)
    recent_commits: list[str] = Field(default_factory=list)
    dirty: bool = False
    top_level: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    test_command: str | None = None
    start_command: str | None = None
    is_web: bool = False
    web_hints: list[str] = Field(default_factory=list)
    constraints_excerpt: str = ""
    stack_notes: str = ""


class EvaluationPart(BaseModel):
    name: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    passed: bool
    tests: EvaluationPart | None = None
    browser: EvaluationPart | None = None
    message: str = ""


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DELIVERY_PARTIAL = "delivery_partial"


class RunReport(BaseModel):
    run_id: str
    status: RunStatus = RunStatus.RUNNING
    task: str
    repo_url: str
    base_branch: str
    workdir: str
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    plan: TaskPlan | None = None
    context: RepoContext | None = None
    iterations: int = 0
    last_evaluation: EvaluationResult | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    delivery_note: str | None = None
    error: str | None = None
    log_tail: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
