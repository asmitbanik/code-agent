"""Retrieve relevant code chunks for a task/subtask."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_auto.rag.embedder import LocalEmbedder
from agent_auto.rag.store import ChromaStore


@dataclass
class ContextPack:
    query: str
    chunks: list[dict[str, Any]]

    def as_prompt_block(self, max_chars: int = 10_000) -> str:
        parts: list[str] = []
        used = 0
        for ch in self.chunks:
            meta = ch.get("metadata") or {}
            header = (
                f"// file: {meta.get('path')} "
                f"L{meta.get('start_line')}-{meta.get('end_line')} "
                f"({meta.get('symbol')})"
            )
            body = ch.get("text") or ""
            block = f"{header}\n{body}\n"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n".join(parts) if parts else "(no retrieved chunks)"


class Retriever:
    def __init__(self, store: ChromaStore, embedder: LocalEmbedder | None = None) -> None:
        self.store = store
        self.embedder = embedder or LocalEmbedder()

    def retrieve(self, query: str, k: int = 10) -> ContextPack:
        embedding = self.embedder.embed_query(query)
        hits = self.store.query(embedding, n_results=k)
        return ContextPack(query=query, chunks=hits)
