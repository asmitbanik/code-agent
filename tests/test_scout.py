"""Scout heuristics tests."""

from pathlib import Path

from agent_auto.context.scout import (
    _detect_languages,
    _detect_package_managers,
    _detect_test_command,
    _detect_web,
)


def test_detect_python_and_pytest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    names = {p.name for p in tmp_path.iterdir()}
    assert "python" in _detect_languages(tmp_path, names)
    assert _detect_test_command(tmp_path, names, {}) == "pytest -q"


def test_detect_npm_web(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"next":"14.0.0"},"scripts":{"dev":"next dev","test":"jest"}}',
        encoding="utf-8",
    )
    names = {p.name for p in tmp_path.iterdir()}
    scripts = {"dev": "next dev", "test": "jest"}
    assert "npm" in _detect_package_managers(names)
    assert _detect_test_command(tmp_path, names, scripts) == "npm test"
    is_web, hints = _detect_web(tmp_path, names, scripts)
    assert is_web
    assert "next.js" in hints
