"""Heuristic task classification and requirements — no LLM by default."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_auto.models import RepoContext, Subtask, TaskPlan


@dataclass
class TaskClass:
    """Backward-compatible wrapper; kind maps to complexity tier."""

    kind: str  # docs | simple | standard | complex
    target_files: list[str]
    skip_browser: bool
    skip_tests: bool
    use_llm: bool
    reason: str
    confidence: float = 0.9

    @property
    def complexity(self) -> str:
        return self.kind


@dataclass
class TaskRequirements:
    complexity: str
    reason: str
    confidence: float = 0.9
    target_files: list[str] = field(default_factory=list)
    needs_db: bool = False
    needs_auth: bool = False
    needs_browser: bool = False
    needs_node_install: bool = False
    needs_python_install: bool = False
    skip_browser: bool = False
    skip_tests: bool = False
    use_llm: bool = True
    env_keys_required: list[str] = field(default_factory=list)
    dep_commands: list[str] = field(default_factory=list)

    def to_task_class(self) -> TaskClass:
        return TaskClass(
            kind=self.complexity,
            target_files=self.target_files,
            skip_browser=self.skip_browser,
            skip_tests=self.skip_tests,
            use_llm=self.use_llm,
            reason=self.reason,
            confidence=self.confidence,
        )


_DOCS_PATTERNS = [
    r"\breadme\b",
    r"\bdocs?\b",
    r"\bdocumentation\b",
    r"\bmarkdown\b",
    r"\.md\b",
    r"\bchangelog\b",
    r"\blicense\b",
]

_SIMPLE_PATTERNS = [
    r"\btypo\b",
    r"\brename\b",
    r"\bwording\b",
    r"\bcomment\b",
    r"\bconfig\b",
    r"\bsingle[- ]file\b",
    r"\bfix (a |an |the )?typo\b",
]

_COMPLEX_PATTERNS = [
    r"\bauth(entication|orization)?\b",
    r"\bjwt\b",
    r"\boauth\b",
    r"\bmigration\b",
    r"\bdatabase\b",
    r"\bprisma\b",
    r"\bpassword reset\b",
    r"\bmulti[- ]tenant\b",
    r"\bpayment\b",
    r"\binfrastructure\b",
]

_STANDARD_PATTERNS = [
    r"\bimplement\b",
    r"\badd (a |an |the )?(feature|endpoint|api|component|button|page|route)\b",
    r"\bfix (a |an |the )?(bug|error|issue|crash)\b",
    r"\brefactor\b",
    r"\btest(s)?\b",
]


def classify_task(task: str) -> TaskClass:
    return analyze_task(task).to_task_class()


def analyze_task(task: str, context: RepoContext | None = None) -> TaskRequirements:
    text = task.lower()
    docs_hit = any(re.search(p, text) for p in _DOCS_PATTERNS)
    simple_hit = any(re.search(p, text) for p in _SIMPLE_PATTERNS)
    complex_hit = any(re.search(p, text) for p in _COMPLEX_PATTERNS)
    standard_hit = any(re.search(p, text) for p in _STANDARD_PATTERNS)
    code_hit = standard_hit or complex_hit

    only_readme = bool(
        re.search(r"only\s+readme|readme\.md|change the readme|rewrite.*(readme)", text)
    ) or (docs_hit and not code_hit and re.search(r"readme", text))

    if only_readme or (docs_hit and not code_hit and "readme" in text):
        return TaskRequirements(
            complexity="docs",
            reason="Docs/README-only task",
            confidence=0.95,
            target_files=["README.md"],
            skip_browser=True,
            skip_tests=True,
            use_llm=True,
        )

    if docs_hit and not code_hit:
        return TaskRequirements(
            complexity="docs",
            reason="Documentation-only task",
            confidence=0.9,
            skip_browser=True,
            skip_tests=True,
            use_llm=True,
        )

    needs_auth = bool(re.search(r"\bauth|jwt|oauth|login|password|supabase\b", text))
    needs_db = bool(re.search(r"\bdb|database|migration|prisma|postgres|sql\b", text))
    needs_browser = bool(re.search(r"\bui|frontend|page|button|browser|css\b", text))

    if complex_hit or (needs_auth and needs_db):
        complexity = "complex"
        reason = "Auth/DB/migration or multi-system task"
        confidence = 0.85
    elif simple_hit and not standard_hit and not complex_hit:
        complexity = "simple"
        reason = "Small single-scope edit"
        confidence = 0.8
    elif standard_hit or code_hit:
        complexity = "standard"
        reason = "Feature/bugfix coding task"
        confidence = 0.8
    else:
        complexity = "standard"
        reason = "Default standard complexity (low-confidence heuristic)"
        confidence = 0.55

    req = TaskRequirements(
        complexity=complexity,
        reason=reason,
        confidence=confidence,
        needs_db=needs_db,
        needs_auth=needs_auth,
        needs_browser=needs_browser or (context.is_web if context else False),
        skip_browser=complexity == "simple",
        skip_tests=complexity == "simple",
        use_llm=True,
    )
    if context:
        enrich_requirements_from_context(req, context)
    return req


def enrich_requirements_from_context(req: TaskRequirements, context: RepoContext) -> None:
    root = Path(context.workdir)
    if "javascript/typescript" in context.languages or "npm" in context.package_managers:
        req.needs_node_install = (root / "package.json").exists()
    if "python" in context.languages:
        req.needs_python_install = (
            (root / "pyproject.toml").exists() or (root / "requirements.txt").exists()
        )
    if context.is_web and req.complexity in {"standard", "complex"}:
        req.needs_browser = True
    if any(x in context.stack_notes for x in ("prisma", "postgres", "supabase")):
        req.needs_db = True

    req.env_keys_required = collect_env_example_keys(root)
    cmds: list[str] = []
    if req.needs_node_install:
        cmds.append("npm install")
    if req.needs_python_install:
        if (root / "requirements.txt").exists():
            cmds.append("pip install -r requirements.txt")
        else:
            cmds.append("pip install -e .")
    if req.needs_db and (root / "package.json").exists():
        # common script; intake will confirm
        cmds.append("npm run db:push")
    req.dep_commands = cmds


def collect_env_example_keys(root: Path) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for path in [
        root / ".env.example",
        root / "client" / ".env.example",
        root / "server" / ".env.example",
        root / "api" / ".env.example",
    ]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def heuristic_plan(task: str, task_class: TaskClass) -> TaskPlan:
    if task_class.kind == "docs":
        targets = ", ".join(task_class.target_files) or "documentation files"
        return TaskPlan(
            goal=task.strip()[:240],
            success_criteria=[
                f"Update {targets}",
                "No application source code changes",
            ],
            subtasks=[
                Subtask(
                    id="1",
                    title=f"Rewrite {targets}",
                    done_when="File(s) updated and ready to ship",
                    status="pending",
                )
            ],
            browser_checks=[],
        )

    if task_class.kind == "simple":
        return TaskPlan(
            goal=task.strip()[:240],
            success_criteria=["Change applied", "Review approved"],
            subtasks=[
                Subtask(id="1", title="Apply small edit", done_when="file updated"),
            ],
            browser_checks=[],
        )

    return TaskPlan(
        goal=task.strip()[:240],
        success_criteria=["tests pass", "task completed"],
        subtasks=[
            Subtask(id="1", title="Locate relevant files", done_when="files identified"),
            Subtask(id="2", title="Implement changes", done_when="code updated"),
            Subtask(id="3", title="Verify", done_when="checks pass"),
        ],
        browser_checks=[],
    )
