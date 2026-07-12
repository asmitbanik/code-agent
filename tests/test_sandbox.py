"""Unit tests for path sandboxing."""

from pathlib import Path

import pytest

from agent_auto.tools.sandbox import SandboxError, resolve_in_sandbox


def test_resolve_relative(tmp_path: Path) -> None:
    target = resolve_in_sandbox(tmp_path, "src/app.py")
    assert target == (tmp_path / "src" / "app.py").resolve()


def test_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        resolve_in_sandbox(tmp_path, "../outside.txt")
