"""Preflight checks for local/Docker environments."""

from __future__ import annotations

import shutil

from rich.console import Console

from agent_auto.config import get_settings


def _ok(console: Console, label: str, fine: bool, detail: str = "") -> bool:
    mark = "[green]OK[/green]" if fine else "[red]MISSING[/red]"
    suffix = f" - {detail}" if detail else ""
    console.print(f"  {mark}  {label}{suffix}")
    return fine


def run_doctor(console: Console) -> bool:
    console.print("[bold]agent-auto doctor[/bold]")
    settings = get_settings()
    all_ok = True
    provider = settings.llm_provider.strip().lower()

    console.print(f"  provider: {provider}")
    if provider == "groq":
        all_ok &= _ok(console, "GROQ_API_KEY", bool(settings.groq_api_key.strip()))
        console.print(f"  model: {settings.groq_model}")
    else:
        all_ok &= _ok(console, "GEMINI_API_KEY", bool(settings.gemini_api_key.strip()))
        console.print(f"  model: {settings.gemini_model}")

    all_ok &= _ok(console, "git", shutil.which("git") is not None, shutil.which("git") or "")
    gh = shutil.which("gh")
    _ok(console, "gh (for PRs)", gh is not None, gh or "install GitHub CLI for PR creation")
    if settings.github_auth_token:
        _ok(console, "GH_TOKEN / GITHUB_TOKEN", True, "set")
    else:
        console.print("  [yellow]WARN[/yellow]  GH_TOKEN not set - push/PR will be skipped")

    try:
        import chromadb  # noqa: F401

        _ok(console, "chromadb", True)
    except Exception as exc:  # noqa: BLE001
        all_ok &= _ok(console, "chromadb", False, str(exc))

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401

        _ok(console, "sentence-transformers", True)
    except Exception as exc:  # noqa: BLE001
        all_ok &= _ok(console, "sentence-transformers", False, str(exc))

    rg = shutil.which("rg")
    _ok(console, "ripgrep (optional)", rg is not None, rg or "Python search fallback will be used")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _ok(console, "Playwright Chromium", True)
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [yellow]WARN[/yellow]  Playwright Chromium - {exc}")

    node = shutil.which("node")
    _ok(console, "node (for JS target repos)", node is not None, node or "optional")
    console.print(f"  max_iterations: {settings.agent_max_iterations}")
    return all_ok
