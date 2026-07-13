"""Claim issues with a comment after substantial progress."""

from __future__ import annotations

import subprocess


def claim_issue(repo: str, issue_number: int) -> bool:
    body = (
        "Working on this — substantial progress locally; "
        "will open a PR shortly with verification notes."
    )
    r = subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", body],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return r.returncode == 0
