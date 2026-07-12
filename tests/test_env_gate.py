"""Env example parsing."""

from pathlib import Path

from agent_auto.intake.env_gate import parse_env_file, find_env_examples


def test_parse_env_file(tmp_path: Path) -> None:
    p = tmp_path / ".env.example"
    p.write_text("FOO=bar\n# comment\nSECRET_KEY=\n", encoding="utf-8")
    data = parse_env_file(p)
    assert data["FOO"] == "bar"
    assert data["SECRET_KEY"] == ""


def test_find_env_examples(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / ".env.example").write_text("B=2\n", encoding="utf-8")
    found = find_env_examples(tmp_path)
    assert len(found) == 2
