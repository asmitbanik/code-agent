"""Chunker unit tests (no embeddings required)."""

from pathlib import Path

from agent_auto.rag.chunker import chunk_file, chunk_repository


def test_chunk_python_functions(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text(
        "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n",
        encoding="utf-8",
    )
    chunks = chunk_file(tmp_path, src)
    assert len(chunks) >= 2
    assert any("alpha" in c.symbol for c in chunks)


def test_chunk_repository_skips_node_modules(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    nm = tmp_path / "node_modules" / "x"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("export const x = 1\n", encoding="utf-8")
    chunks = chunk_repository(tmp_path)
    assert all("node_modules" not in c.path for c in chunks)
    assert any(c.path.endswith("app.py") for c in chunks)
