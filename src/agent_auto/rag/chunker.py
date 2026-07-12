"""Code chunking for RAG indexing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
    "__pycache__",
    ".chroma",
    "chroma",
    "target",
    ".turbo",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".lock",
}

CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".sql",
    ".prisma",
    ".css",
    ".scss",
    ".html",
}


@dataclass
class CodeChunk:
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    text: str
    symbol: str
    language: str


def _lang_for(path: Path) -> str:
    return path.suffix.lstrip(".") or "text"


def _symbol_chunks(path: Path, text: str, language: str) -> list[CodeChunk]:
    """Split by class/function headers using lightweight regex."""
    lines = text.splitlines()
    if language in {"py"}:
        pattern = re.compile(r"^(class |def |async def )")
    elif language in {"ts", "tsx", "js", "jsx"}:
        pattern = re.compile(
            r"^(export )?(default )?(async )?(function |class |const \w+.*=\s*(async )?\(|export class )"
        )
    else:
        return []

    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if pattern.match(line):
            symbol = line.strip()[:120]
            starts.append((i, symbol))
    if not starts:
        return []

    chunks: list[CodeChunk] = []
    for idx, (start, symbol) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        # Keep chunks reasonably sized
        body_lines = lines[start:end]
        if len(body_lines) > 160:
            body_lines = body_lines[:160]
            end = start + len(body_lines)
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        chunks.append(
            CodeChunk(
                chunk_id=f"{path.as_posix()}:{start + 1}-{end}",
                path=path.as_posix(),
                start_line=start + 1,
                end_line=end,
                text=body,
                symbol=symbol,
                language=language,
            )
        )
    return chunks


def _window_chunks(path: Path, text: str, language: str, window: int = 100, overlap: int = 20) -> list[CodeChunk]:
    lines = text.splitlines()
    if not lines:
        return []
    chunks: list[CodeChunk] = []
    step = max(1, window - overlap)
    for start in range(0, len(lines), step):
        end = min(len(lines), start + window)
        body = "\n".join(lines[start:end]).strip()
        if not body:
            continue
        chunks.append(
            CodeChunk(
                chunk_id=f"{path.as_posix()}:{start + 1}-{end}",
                path=path.as_posix(),
                start_line=start + 1,
                end_line=end,
                text=body,
                symbol=f"lines {start + 1}-{end}",
                language=language,
            )
        )
        if end >= len(lines):
            break
    return chunks


def chunk_file(root: Path, path: Path, max_chars: int = 12_000) -> list[CodeChunk]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    if not text.strip():
        return []
    if len(text) > max_chars * 4:
        text = text[: max_chars * 4]
    rel = path.relative_to(root)
    language = _lang_for(path)
    chunks = _symbol_chunks(rel, text, language)
    if not chunks:
        chunks = _window_chunks(rel, text, language)
    # Truncate oversized chunk text
    for c in chunks:
        if len(c.text) > max_chars:
            c.text = c.text[:max_chars]
    return chunks


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.suffix.lower() not in CODE_SUFFIXES and path.name not in {
            "Dockerfile",
            "Makefile",
        }:
            continue
        # skip huge files
        try:
            if path.stat().st_size > 400_000:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def chunk_repository(root: Path) -> list[CodeChunk]:
    all_chunks: list[CodeChunk] = []
    for path in iter_source_files(root):
        all_chunks.extend(chunk_file(root, path))
    return all_chunks
