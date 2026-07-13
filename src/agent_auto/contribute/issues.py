"""GitHub issue models and fetch via gh CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IssueAssignee:
    login: str


@dataclass
class LinkedPR:
    number: int
    url: str
    author: str
    state: str  # OPEN | MERGED | CLOSED


@dataclass
class GitHubIssue:
    number: int
    title: str
    body: str
    url: str
    labels: list[str] = field(default_factory=list)
    assignees: list[IssueAssignee] = field(default_factory=list)
    linked_prs: list[LinkedPR] = field(default_factory=list)
    complexity: str = "standard"
    skip_reason: str | None = None

    @property
    def assignee_logins(self) -> list[str]:
        return [a.login for a in self.assignees]


def _gh_json(args: list[str], timeout: int = 120) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "gh failed")
    text = (result.stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def parse_repo_slug(repo: str) -> tuple[str, str]:
    """Accept owner/name or https://github.com/owner/name(.git)."""
    raw = repo.strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "github.com" in raw:
        parts = raw.split("github.com/")[-1].split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
    if "/" in raw:
        owner, name = raw.split("/", 1)
        return owner, name.split("/")[0]
    raise ValueError(f"Invalid repo slug: {repo}")


def gh_whoami() -> str:
    data = _gh_json(["api", "user"])
    return str(data.get("login") or "")


def fetch_open_issues(
    owner: str,
    name: str,
    *,
    limit: int = 50,
    labels: list[str] | None = None,
) -> list[GitHubIssue]:
    repo = f"{owner}/{name}"
    args = [
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(max(limit * 3, 30)),
        "--json",
        "number,title,body,url,labels,assignees",
    ]
    if labels:
        for lab in labels:
            args.extend(["--label", lab.strip()])
    raw = _gh_json(args) or []
    issues: list[GitHubIssue] = []
    for item in raw:
        labs = [str(x.get("name") or "") for x in (item.get("labels") or [])]
        assignees = [
            IssueAssignee(login=str(a.get("login") or ""))
            for a in (item.get("assignees") or [])
            if a.get("login")
        ]
        issues.append(
            GitHubIssue(
                number=int(item["number"]),
                title=str(item.get("title") or ""),
                body=str(item.get("body") or ""),
                url=str(item.get("url") or ""),
                labels=labs,
                assignees=assignees,
            )
        )
    return issues


def enrich_linked_prs(owner: str, name: str, issues: list[GitHubIssue]) -> None:
    """Attach open PRs that mention Fixes/Closes #<n> for each issue."""
    repo = f"{owner}/{name}"
    try:
        prs = _gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,url,author,body,title,state",
            ]
        ) or []
    except RuntimeError:
        prs = []

    by_issue: dict[int, list[LinkedPR]] = {i.number: [] for i in issues}
    for pr in prs:
        text = f"{pr.get('title') or ''}\n{pr.get('body') or ''}".lower()
        author = str((pr.get("author") or {}).get("login") or "")
        linked = LinkedPR(
            number=int(pr["number"]),
            url=str(pr.get("url") or ""),
            author=author,
            state="OPEN",
        )
        for issue in issues:
            needles = (
                f"fixes #{issue.number}",
                f"closes #{issue.number}",
                f"resolves #{issue.number}",
                f"fix #{issue.number}",
            )
            if any(n in text for n in needles):
                by_issue[issue.number].append(linked)

    for issue in issues:
        issue.linked_prs = by_issue.get(issue.number, [])


def issue_to_task(issue: GitHubIssue) -> str:
    body = (issue.body or "").strip()
    if len(body) > 4000:
        body = body[:4000] + "\n\n[truncated]"
    return (
        f"GitHub Issue #{issue.number}: {issue.title}\n\n"
        f"{body}\n\n"
        "Acceptance: resolve this issue completely; do not expand scope. "
        "Prefer well-tested, production-quality changes."
    )
