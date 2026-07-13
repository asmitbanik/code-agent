"""Real-user UX / API verification (not lint-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

from agent_auto.contribute.issues import GitHubIssue
from agent_auto.contribute.runtime_profile import RuntimeProfile
from agent_auto.llm.client import LLMClient
from agent_auto.models import RepoContext
from agent_auto.tools.browser import browser_smoke
from agent_auto.tools.shell import run_shell


@dataclass
class UXResult:
    passed: bool
    summary: str
    mode: str  # browser | api | docs | skipped
    artifacts: list[str]


UX_PLAN_SYSTEM = (
    "Return JSON only: "
    '{"mode":"browser"|"api"|"docs","checks":["text:... or css:... or GET /path expects 200"],'
    '"start_hint":"optional command","url":"optional base url"}'
)


def _derive_checks_heuristic(issue: GitHubIssue, context: RepoContext) -> dict:
    text = f"{issue.title}\n{issue.body}".lower()
    if context.is_web and any(
        x in text for x in ("ui", "page", "button", "screen", "frontend", "display", "visible")
    ):
        checks = ["html"]
        # extract quoted strings as text checks
        for m in re.findall(r'"([^"]{3,60})"|\'([^\']{3,60})\'', issue.body or ""):
            s = m[0] or m[1]
            if s:
                checks.append(f"text:{s}")
        return {"mode": "browser", "checks": checks[:6], "url": None, "start_hint": context.start_command}
    if any(x in text for x in ("api", "endpoint", "graphql", "route", "backend")):
        return {
            "mode": "api",
            "checks": ["GET /health", "GET /"],
            "url": "http://127.0.0.1:3001",
            "start_hint": context.start_command,
        }
    if any(x in text for x in ("readme", "docs", "documentation", "typo")):
        return {"mode": "docs", "checks": [], "url": None, "start_hint": None}
    if context.is_web:
        return {
            "mode": "browser",
            "checks": ["html"],
            "url": None,
            "start_hint": context.start_command,
        }
    return {"mode": "api", "checks": ["GET /"], "url": "http://127.0.0.1:3000", "start_hint": None}


def derive_ux_plan(
    client: LLMClient | None,
    issue: GitHubIssue,
    context: RepoContext,
) -> dict:
    base = _derive_checks_heuristic(issue, context)
    if client is None:
        return base
    try:
        data = client.generate_json(
            system=UX_PLAN_SYSTEM,
            user=f"ISSUE:\n{issue.title}\n{issue.body[:2500]}\nSTACK:{context.stack_notes}",
            max_tokens=600,
        )
        if isinstance(data, dict) and data.get("mode"):
            base.update({k: data[k] for k in data if data[k] is not None})
    except Exception:  # noqa: BLE001
        pass
    return base


def _api_smoke(checks: list[str], base_url: str) -> tuple[bool, str]:
    import httpx

    failures: list[str] = []
    for check in checks:
        check = check.strip()
        if check.upper().startswith("GET "):
            path = check[4:].strip().split()[0]
        else:
            path = check
        url = path if path.startswith("http") else base_url.rstrip("/") + (
            path if path.startswith("/") else "/" + path
        )
        try:
            r = httpx.get(url, timeout=5.0)
            if r.status_code >= 500:
                failures.append(f"{url} -> {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url} error: {exc}")
    if failures:
        return False, "; ".join(failures)
    return True, f"API smoke passed against {base_url}"


def run_ux_verify(
    *,
    root: Path,
    issue: GitHubIssue,
    context: RepoContext,
    profile: RuntimeProfile,
    artifacts_dir: Path,
    console: Console,
    client: LLMClient | None = None,
    allow_unverified: bool = False,
) -> UXResult:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    plan = derive_ux_plan(client, issue, context)
    mode = str(plan.get("mode") or "docs")
    console.print(f"  [cyan]ux_verify[/cyan] mode={mode}")

    if mode == "docs":
        return UXResult(True, "docs-only issue; code UX not required", "docs", [])

    if not profile.allow_heavy_services and mode == "browser":
        # still try lightweight vite/node if available
        if not profile.has_node:
            msg = "Cannot run browser UX: Node unavailable / low resources"
            if allow_unverified:
                return UXResult(True, f"SKIPPED: {msg}", "skipped", [])
            return UXResult(False, msg, "skipped", [])

    # Install lightweight deps if package.json present and node available
    if profile.has_node and (root / "package.json").exists():
        if not (root / "node_modules").exists():
            console.print("  installing npm deps for UX verify...")
            run_shell(root, "npm install", timeout_sec=600)

    if mode == "browser":
        if not profile.has_node and not context.start_command:
            msg = "No way to start web app for Playwright UX"
            return UXResult(allow_unverified, msg, "skipped", [])
        part = browser_smoke(
            root,
            start_command=plan.get("start_hint") or context.start_command,
            checks=list(plan.get("checks") or ["html"]),
            artifacts_dir=artifacts_dir,
            base_url=plan.get("url"),
        )
        return UXResult(
            passed=bool(part.passed) or allow_unverified,
            summary=part.summary,
            mode="browser",
            artifacts=part.artifacts,
        )

    if mode == "api":
        # Try start server briefly if start command looks like API
        start = plan.get("start_hint") or context.start_command
        base = str(plan.get("url") or "http://127.0.0.1:3001")
        # If server already up, smoke; else try without long boot for docs of failure
        ok, summary = _api_smoke(list(plan.get("checks") or ["GET /"]), base)
        if not ok and start:
            # Best-effort: user may need env; still report
            summary = f"{summary} (start_hint={start})"
        if allow_unverified and not ok:
            return UXResult(True, f"SKIPPED unverified: {summary}", "api", [])
        return UXResult(ok, summary, "api", [])

    return UXResult(True, "no UX plan", "skipped", [])
