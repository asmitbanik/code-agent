"""Bounded shell execution inside the workspace."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

BLOCKED_PATTERNS = [
    re.compile(r"git\s+push\s+.*--force"),
    re.compile(r"git\s+reset\s+--hard"),
    re.compile(r"git\s+clean\s+-.*f"),
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"shutdown"),
    re.compile(r"mkfs"),
    re.compile(r":\(\)\s*\{"),  # fork bomb
]


def run_shell(
    root: Path,
    command: str,
    *,
    timeout_sec: int = 300,
    max_output_chars: int = 20_000,
) -> dict:
    cmd = command.strip()
    if not cmd:
        return {"ok": False, "error": "Empty command"}
    for pat in BLOCKED_PATTERNS:
        if pat.search(cmd):
            return {"ok": False, "error": f"Blocked dangerous command pattern: {pat.pattern}"}

    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout_sec}s", "command": cmd}

    stdout = (result.stdout or "")[-max_output_chars:]
    stderr = (result.stderr or "")[-max_output_chars:]
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "command": cmd,
    }
