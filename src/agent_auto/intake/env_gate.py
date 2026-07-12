"""Interactive env / dependency intake from target .env.example files."""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

from agent_auto.classify import TaskRequirements


SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, val = raw.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def find_env_examples(root: Path) -> list[Path]:
    candidates = [
        root / ".env.example",
        root / "client" / ".env.example",
        root / "server" / ".env.example",
        root / "api" / ".env.example",
    ]
    return [p for p in candidates if p.is_file()]


def _is_secret(key: str) -> bool:
    upper = key.upper()
    return any(h in upper for h in SECRET_HINTS)


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_env_gate(
    *,
    root: Path,
    requirements: TaskRequirements,
    console: Console,
    env_file: Path | None = None,
    assume_yes: bool = False,
) -> dict[str, str]:
    """Fill missing env vars interactively; write repo .env files.

    Non-TTY without --env-file raises RuntimeError.
    """
    examples = find_env_examples(root)
    if not examples and not requirements.env_keys_required:
        console.print("  [dim]No .env.example found — skipping env gate[/dim]")
        return {}

    provided: dict[str, str] = {}
    if env_file:
        provided.update(parse_env_file(env_file))

    # Also accept already-present repo .env
    existing_root = parse_env_file(root / ".env")
    for k, v in existing_root.items():
        provided.setdefault(k, v)

    # Keys from examples (preserve order)
    ordered_keys: list[str] = []
    example_defaults: dict[str, str] = {}
    for ex in examples:
        parsed = parse_env_file(ex)
        for k, v in parsed.items():
            if k not in ordered_keys:
                ordered_keys.append(k)
            example_defaults.setdefault(k, v)

    for k in requirements.env_keys_required:
        if k not in ordered_keys:
            ordered_keys.append(k)

    missing = [k for k in ordered_keys if not (provided.get(k) or "").strip()]
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if missing and not interactive and not env_file:
        raise RuntimeError(
            "Non-interactive session and missing env vars. "
            "Pass --env-file with values for: " + ", ".join(missing)
        )

    if missing and not interactive and env_file:
        still = [k for k in missing if not (provided.get(k) or "").strip()]
        if still:
            raise RuntimeError(
                "Env file incomplete. Still missing: " + ", ".join(still)
            )

    if missing and interactive:
        console.print("[bold]Env intake[/bold] — fill values from .env.example")
        for key in missing:
            default = example_defaults.get(key, "")
            password = _is_secret(key)
            if password:
                val = Prompt.ask(f"  {key}", password=True)
            else:
                val = Prompt.ask(f"  {key}", default=default or "")
            provided[key] = val

    # Write root .env
    if ordered_keys:
        root_values = {k: provided.get(k, example_defaults.get(k, "")) for k in ordered_keys}
        # Prefer keys that belong to root example
        root_example = root / ".env.example"
        if root_example.is_file():
            root_keys = list(parse_env_file(root_example).keys())
            _write_env(root / ".env", {k: root_values.get(k, "") for k in root_keys})
        else:
            _write_env(root / ".env", root_values)

        client_example = root / "client" / ".env.example"
        if client_example.is_file():
            client_keys = list(parse_env_file(client_example).keys())
            _write_env(
                root / "client" / ".env",
                {k: provided.get(k, "") for k in client_keys},
            )

        console.print(f"  wrote env files under {root}")

    # Dependency confirmation
    cmds = list(requirements.dep_commands)
    if cmds:
        console.print("[bold]Dependency plan[/bold]")
        for c in cmds:
            console.print(f"  - {c}")
        if assume_yes:
            run = True
        elif interactive:
            run = Confirm.ask("Run these install/setup commands now?", default=True)
        else:
            run = False
            console.print("  [yellow]Skipping installs in non-interactive mode[/yellow]")

        if run:
            from agent_auto.tools.shell import run_shell

            for c in cmds:
                console.print(f"  running: {c}")
                result = run_shell(root, c, timeout_sec=600)
                if not result.get("ok"):
                    console.print(
                        f"  [yellow]warn:[/yellow] {c} failed: "
                        f"{(result.get('stderr') or result.get('error') or '')[:300]}"
                    )

    return provided
