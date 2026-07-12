"""Index a repository into ChromaDB."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.console import Console

from agent_auto.rag.chunker import chunk_repository
from agent_auto.rag.embedder import LocalEmbedder
from agent_auto.rag.store import ChromaStore


def _git_head(root: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return (r.stdout or "").strip() or "unknown"


def index_repository(
    *,
    root: Path,
    chroma_dir: Path,
    console: Console | None = None,
    embedder: LocalEmbedder | None = None,
) -> ChromaStore:
    console = console or Console()
    embedder = embedder or LocalEmbedder()
    store = ChromaStore(chroma_dir)
    meta_path = chroma_dir / "index_meta.json"
    head = _git_head(root)

    if meta_path.is_file():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
            if prev.get("git_head") == head and store.count() > 0:
                console.print(f"  [dim]RAG index cache hit ({store.count()} chunks)[/dim]")
                return store
        except (OSError, json.JSONDecodeError):
            pass

    console.print("[bold]Indexing[/bold] repository into ChromaDB (local embeddings) ...")
    chunks = chunk_repository(root)
    console.print(f"  chunks: {len(chunks)}")
    store.reset()
    if not chunks:
        meta_path.write_text(json.dumps({"git_head": head, "chunks": 0}), encoding="utf-8")
        return store

    # Embed in batches
    batch = 64
    total = 0
    for i in range(0, len(chunks), batch):
        slice_chunks = chunks[i : i + batch]
        vectors = embedder.embed_documents([c.text for c in slice_chunks])
        total += store.upsert_chunks(slice_chunks, vectors)
        console.print(f"  embedded {min(i + batch, len(chunks))}/{len(chunks)}")

    meta_path.write_text(
        json.dumps({"git_head": head, "chunks": total}),
        encoding="utf-8",
    )
    console.print(f"  indexed {total} chunks at {chroma_dir}")
    return store
