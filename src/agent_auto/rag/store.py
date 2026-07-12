"""ChromaDB persistent store for code chunks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_auto.rag.chunker import CodeChunk


class ChromaStore:
    def __init__(self, persist_dir: Path, collection_name: str = "code_chunks") -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None

    def _ensure(self) -> None:
        if self._collection is not None:
            return
        import chromadb

        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):
        self._ensure()
        return self._collection

    def reset(self) -> None:
        self._ensure()
        assert self._client is not None
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:  # noqa: BLE001
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, chunks: list[CodeChunk], embeddings: list[list[float]]) -> int:
        if not chunks:
            return 0
        self._ensure()
        ids = [c.chunk_id for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {
                "path": c.path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "symbol": c.symbol[:200],
                "language": c.language,
            }
            for c in chunks
        ]
        # Chroma has batch limits; upsert in slices
        batch = 100
        for i in range(0, len(ids), batch):
            self.collection.upsert(
                ids=ids[i : i + batch],
                documents=documents[i : i + batch],
                embeddings=embeddings[i : i + batch],
                metadatas=metadatas[i : i + batch],
            )
        return len(ids)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
    ) -> list[dict[str, Any]]:
        self._ensure()
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, max(1, self.collection.count())),
            include=["documents", "metadatas", "distances"],
        )
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        out: list[dict[str, Any]] = []
        for i, doc in enumerate(docs):
            out.append(
                {
                    "id": ids[i] if i < len(ids) else "",
                    "text": doc,
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": dists[i] if i < len(dists) else None,
                }
            )
        return out

    def count(self) -> int:
        self._ensure()
        return int(self.collection.count())
