"""Fork-first workspace setup for open-source contribution."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoWorkspace:
    owner: str
    name: str
    root: Path
    has_push: bool
    fork_owner: str | None
    default_branch: str
    upstream_repo: str  # owner/name
    head_repo: str  # owner/name used as PR head repo


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
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


def _gh_json(args: list[str]) -> dict | list:
    r = _run(["gh", *args])
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout or "gh failed")
    return json.loads(r.stdout)


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (s or "issue")[:max_len]


def detect_push_access(owner: str, name: str) -> bool:
    try:
        data = _gh_json(["api", f"repos/{owner}/{name}"])
        perms = data.get("permissions") or {}
        return bool(perms.get("push") or perms.get("admin"))
    except Exception:  # noqa: BLE001
        return False


def ensure_workspace(
    *,
    owner: str,
    name: str,
    dest: Path,
    me: str,
    base_branch: str | None = None,
) -> RepoWorkspace:
    dest.mkdir(parents=True, exist_ok=True)
    has_push = detect_push_access(owner, name)
    upstream = f"{owner}/{name}"

    meta = _gh_json(["api", f"repos/{owner}/{name}"])
    default_branch = base_branch or str(meta.get("default_branch") or "main")

    if has_push:
        clone_url = f"https://github.com/{owner}/{name}.git"
        fork_owner = None
        head_repo = upstream
    else:
        # Ensure fork exists
        fork = _run(["gh", "repo", "fork", upstream, "--clone=false", "--remote=false"])
        # fork may already exist (exit non-zero); ignore
        clone_url = f"https://github.com/{me}/{name}.git"
        fork_owner = me
        head_repo = f"{me}/{name}"

    if (dest / ".git").exists():
        root = dest
        _run(["git", "fetch", "--all", "--prune"], cwd=root, timeout=300)
    else:
        r = _run(["git", "clone", "--depth", "50", clone_url, str(dest)], timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"clone failed: {r.stderr or r.stdout}")
        root = dest

    # Remotes
    if not has_push:
        # origin = fork, upstream = original
        _run(["git", "remote", "remove", "upstream"], cwd=root)
        _run(
            ["git", "remote", "add", "upstream", f"https://github.com/{owner}/{name}.git"],
            cwd=root,
        )
        _run(["git", "fetch", "upstream", default_branch], cwd=root, timeout=180)
    else:
        _run(["git", "fetch", "origin", default_branch], cwd=root, timeout=180)

    return RepoWorkspace(
        owner=owner,
        name=name,
        root=root,
        has_push=has_push,
        fork_owner=fork_owner,
        default_branch=default_branch,
        upstream_repo=upstream,
        head_repo=head_repo,
    )


def checkout_issue_branch(ws: RepoWorkspace, issue_number: int, title: str) -> str:
    branch = f"agent/issue-{issue_number}-{slugify(title)}"
    root = ws.root
    # Sync from upstream/origin default
    if ws.has_push:
        _run(["git", "checkout", ws.default_branch], cwd=root)
        _run(["git", "pull", "origin", ws.default_branch], cwd=root, timeout=180)
        base_ref = ws.default_branch
    else:
        _run(["git", "fetch", "upstream", ws.default_branch], cwd=root, timeout=180)
        base_ref = f"upstream/{ws.default_branch}"

    r = _run(["git", "checkout", "-B", branch, base_ref], cwd=root)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or "failed to create issue branch")
    return branch
