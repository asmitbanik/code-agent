"""Playwright browser smoke checks."""

from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path

import httpx

from agent_auto.models import EvaluationPart


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout_sec: float = 60.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def browser_smoke(
    root: Path,
    *,
    start_command: str | None,
    checks: list[str],
    artifacts_dir: Path,
    base_url: str | None = None,
    timeout_sec: int = 90,
) -> EvaluationPart:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    proc: subprocess.Popen[str] | None = None
    url = base_url
    port: int | None = None

    try:
        if not url:
            if not start_command:
                return EvaluationPart(
                    name="browser",
                    passed=False,
                    summary="Web app detected but no start/dev command found.",
                )
            port = _free_port()
            env_cmd = (
                f"PORT={port} {start_command}"
                if "PORT=" not in start_command
                else start_command
            )
            # Common frameworks honor PORT; also try appending --port
            if "npm" in start_command or "pnpm" in start_command or "yarn" in start_command:
                if "--port" not in start_command and "-p " not in start_command:
                    env_cmd = f"{start_command} -- --port {port}"
            proc = subprocess.Popen(
                env_cmd,
                cwd=str(root),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            url = f"http://127.0.0.1:{port}"
            if not _wait_http(url, timeout_sec=min(timeout_sec, 60)):
                # Try common alternate ports if framework ignored PORT
                for alt in (3000, 5173, 8000, 8080):
                    alt_url = f"http://127.0.0.1:{alt}"
                    if _wait_http(alt_url, timeout_sec=3):
                        url = alt_url
                        break
                else:
                    return EvaluationPart(
                        name="browser",
                        passed=False,
                        summary=f"Dev server did not become ready at {url}",
                    )

        from playwright.sync_api import sync_playwright

        failures: list[str] = []
        screenshot = artifacts_dir / "browser_smoke.png"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            page.screenshot(path=str(screenshot), full_page=True)
            body = page.content()
            visible = page.inner_text("body")
            for check in checks or ["html"]:
                check = check.strip()
                if not check:
                    continue
                if check.startswith("css:"):
                    sel = check[4:].strip()
                    if page.locator(sel).count() == 0:
                        failures.append(f"Missing CSS selector: {sel}")
                elif check.startswith("text:"):
                    needle = check[5:].strip()
                    if needle.lower() not in visible.lower():
                        failures.append(f"Missing text: {needle}")
                else:
                    # Treat as text or substring in HTML
                    if check.lower() not in visible.lower() and check not in body:
                        failures.append(f"Missing check: {check}")
            browser.close()

        if failures:
            return EvaluationPart(
                name="browser",
                passed=False,
                summary="; ".join(failures),
                artifacts=[str(screenshot)],
            )
        return EvaluationPart(
            name="browser",
            passed=True,
            summary=f"Browser smoke passed at {url}",
            artifacts=[str(screenshot)],
        )
    except Exception as exc:  # noqa: BLE001
        return EvaluationPart(
            name="browser",
            passed=False,
            summary=f"Browser smoke error: {exc}",
        )
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
