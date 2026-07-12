"""Filesystem tools sandboxed to the repo workdir."""

from __future__ import annotations

from pathlib import Path

from agent_auto.tools.sandbox import SandboxError, resolve_in_sandbox


def list_dir(root: Path, path: str = ".", max_entries: int = 200) -> dict:
    try:
        target = resolve_in_sandbox(root, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.exists():
        return {"ok": False, "error": f"Not found: {path}"}
    if not target.is_dir():
        return {"ok": False, "error": f"Not a directory: {path}"}
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name)[:max_entries]:
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"ok": True, "path": path, "entries": entries}


def read_file(root: Path, path: str, max_chars: int = 40_000) -> dict:
    try:
        target = resolve_in_sandbox(root, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return {
        "ok": True,
        "path": path,
        "content": text[:max_chars],
        "truncated": truncated,
    }


def write_file(root: Path, path: str, content: str) -> dict:
    try:
        target = resolve_in_sandbox(root, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}


def apply_patch(root: Path, path: str, old_text: str, new_text: str) -> dict:
    try:
        target = resolve_in_sandbox(root, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}
    original = target.read_text(encoding="utf-8", errors="replace")
    if old_text not in original:
        return {
            "ok": False,
            "error": "old_text not found in file (ensure exact match)",
            "path": path,
        }
    count = original.count(old_text)
    if count != 1:
        return {
            "ok": False,
            "error": f"old_text matched {count} times; must be unique",
            "path": path,
        }
    updated = original.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")
    return {"ok": True, "path": path, "replaced": True}
