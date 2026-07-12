"""Path sandbox helpers."""

from __future__ import annotations

from pathlib import Path


class SandboxError(ValueError):
    pass


def resolve_in_sandbox(root: Path, relative: str) -> Path:
    root = root.resolve()
    # Absolute paths are remapped if they already live under root
    candidate = Path(relative)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SandboxError(f"Path escapes workspace: {relative}") from exc
    return resolved
