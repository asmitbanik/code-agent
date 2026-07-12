"""Shell safety tests."""

from pathlib import Path

from agent_auto.tools.shell import run_shell


def test_blocks_force_push(tmp_path: Path) -> None:
    result = run_shell(tmp_path, "git push --force origin main")
    assert result["ok"] is False
    assert "Blocked" in result["error"]


def test_blocks_hard_reset(tmp_path: Path) -> None:
    result = run_shell(tmp_path, "git reset --hard HEAD")
    assert result["ok"] is False
