"""Code search via ripgrep with Python fallback."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def search_code(
    root: Path,
    pattern: str,
    glob: str | None = None,
    max_matches: int = 50,
) -> dict:
    if shutil.which("rg"):
        return _rg_search(root, pattern, glob, max_matches)
    return _python_search(root, pattern, glob, max_matches)


def _rg_search(root: Path, pattern: str, glob: str | None, max_matches: int) -> dict:
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never", "-m", str(max_matches)]
    if glob:
        cmd.extend(["--glob", glob])
    cmd.extend([pattern, str(root)])
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # rg exit 1 = no matches
    if result.returncode not in (0, 1):
        return {"ok": False, "error": result.stderr.strip() or "rg failed"}
    matches = []
    for line in (result.stdout or "").splitlines()[:max_matches]:
        matches.append(line)
    return {"ok": True, "matches": matches, "count": len(matches)}


def _python_search(root: Path, pattern: str, glob: str | None, max_matches: int) -> dict:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "error": f"Invalid regex: {exc}"}

    skip_dirs = {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "__pycache__",
        ".next",
        "target",
    }
    matches: list[str] = []
    for path in root.rglob(glob or "*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                rel = path.relative_to(root).as_posix()
                matches.append(f"{rel}:{i}:{line.strip()[:200]}")
                if len(matches) >= max_matches:
                    return {"ok": True, "matches": matches, "count": len(matches)}
    return {"ok": True, "matches": matches, "count": len(matches)}
