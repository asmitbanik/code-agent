"""Clone repos and scout git/stack/test/web context."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from agent_auto.models import RepoContext


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def clone_repo(repo_url: str, dest: Path, base_branch: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (dest / ".git").exists():
        _run(["git", "fetch", "--all", "--prune"], cwd=dest, timeout=180)
        branch = base_branch or "main"
        checkout = _run(["git", "checkout", branch], cwd=dest)
        if checkout.returncode != 0:
            _run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=dest)
        _run(["git", "reset", "--hard", f"origin/{branch}"], cwd=dest)
        return dest

    cmd = ["git", "clone", "--depth", "50", repo_url, str(dest)]
    if base_branch:
        cmd = ["git", "clone", "--depth", "50", "--branch", base_branch, repo_url, str(dest)]
    result = _run(cmd, timeout=300)
    if result.returncode != 0:
        # Retry without branch pin (branch name may differ)
        if base_branch:
            result = _run(["git", "clone", "--depth", "50", repo_url, str(dest)], timeout=300)
        if result.returncode != 0:
            raise RuntimeError(
                f"git clone failed:\n{result.stderr or result.stdout}"
            )
    return dest


def _git_out(cwd: Path, *args: str) -> str:
    r = _run(["git", *args], cwd=cwd)
    return (r.stdout or "").strip()


def _detect_languages(root: Path, names: set[str]) -> list[str]:
    langs: list[str] = []
    mapping = [
        ("package.json", "javascript/typescript"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
    ]
    for filename, lang in mapping:
        if filename in names:
            langs.append(lang)
    return sorted(set(langs))


def _detect_package_managers(names: set[str]) -> list[str]:
    pms: list[str] = []
    if "pnpm-lock.yaml" in names:
        pms.append("pnpm")
    if "yarn.lock" in names:
        pms.append("yarn")
    if "package-lock.json" in names or "package.json" in names:
        pms.append("npm")
    if "poetry.lock" in names or "pyproject.toml" in names:
        pms.append("pip/poetry")
    if "go.mod" in names:
        pms.append("go")
    if "Cargo.toml" in names:
        pms.append("cargo")
    return pms


def _read_package_scripts(root: Path) -> dict[str, str]:
    pkg = root / "package.json"
    if not pkg.exists():
        return {}
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts") or {}
    return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}


def _detect_test_command(root: Path, names: set[str], scripts: dict[str, str]) -> str | None:
    if "test" in scripts:
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm test"
        if (root / "yarn.lock").exists():
            return "yarn test"
        return "npm test"
    if "pytest" in names or any(root.glob("**/test_*.py")) or (root / "tests").is_dir():
        if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
            return "pytest -q"
        return "python -m pytest -q"
    if "go.mod" in names:
        return "go test ./..."
    if "Cargo.toml" in names:
        return "cargo test"
    if "Makefile" in names:
        mk = (root / "Makefile").read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^test:", mk, re.M):
            return "make test"
    return None


def _detect_start_command(root: Path, scripts: dict[str, str]) -> str | None:
    for key in ("dev", "start", "serve"):
        if key in scripts:
            if (root / "pnpm-lock.yaml").exists():
                return f"pnpm {key}"
            if (root / "yarn.lock").exists():
                return f"yarn {key}"
            return f"npm run {key}"
    if (root / "manage.py").exists():
        return "python manage.py runserver 0.0.0.0:8000"
    return None


def _detect_web(root: Path, names: set[str], scripts: dict[str, str]) -> tuple[bool, list[str]]:
    hints: list[str] = []
    pkg = root / "package.json"
    deps: dict[str, str] = {}
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            for key in ("dependencies", "devDependencies"):
                block = data.get(key) or {}
                if isinstance(block, dict):
                    deps.update({str(k): str(v) for k, v in block.items()})
        except (OSError, json.JSONDecodeError):
            pass

    web_pkgs = {
        "next": "next.js",
        "react": "react",
        "vite": "vite",
        "vue": "vue",
        "@angular/core": "angular",
        "svelte": "svelte",
        "nuxt": "nuxt",
    }
    for pkg_name, label in web_pkgs.items():
        if pkg_name in deps:
            hints.append(label)

    if "manage.py" in names:
        hints.append("django")
    if any(n.endswith(".html") for n in names):
        hints.append("html")
    if "dev" in scripts or "start" in scripts:
        hints.append("node-dev-server")

    return (len(hints) > 0, sorted(set(hints)))


def _constraints_excerpt(root: Path, limit: int = 4000) -> str:
    chunks: list[str] = []
    for name in ("AGENTS.md", "CONTRIBUTING.md", "README.md", "readme.md"):
        path = root / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks.append(f"## {name}\n{text[: limit // max(1, len(chunks) + 1)]}")
    return "\n\n".join(chunks)[:limit]


def scout_repo(repo_url: str, workdir: Path) -> RepoContext:
    names = {p.name for p in workdir.iterdir()}
    top_level = sorted(names)[:80]
    scripts = _read_package_scripts(workdir)
    languages = _detect_languages(workdir, names)
    pms = _detect_package_managers(names)
    test_cmd = _detect_test_command(workdir, names, scripts)
    start_cmd = _detect_start_command(workdir, scripts)
    is_web, web_hints = _detect_web(workdir, names, scripts)

    current = _git_out(workdir, "rev-parse", "--abbrev-ref", "HEAD")
    remotes = [ln.strip() for ln in _git_out(workdir, "remote", "-v").splitlines() if ln.strip()]
    recent = [
        ln.strip()
        for ln in _git_out(workdir, "log", "-5", "--oneline").splitlines()
        if ln.strip()
    ]
    status = _git_out(workdir, "status", "--porcelain")
    default = "main"
    show = _git_out(workdir, "symbolic-ref", "refs/remotes/origin/HEAD")
    if show:
        default = show.rsplit("/", 1)[-1]
    elif _run(["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/main"], cwd=workdir).returncode == 0:
        default = "main"
    elif _run(["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/master"], cwd=workdir).returncode == 0:
        default = "master"

    stack_notes = (
        f"languages={languages}; package_managers={pms}; "
        f"test_command={test_cmd}; start_command={start_cmd}; "
        f"is_web={is_web}; web_hints={web_hints}"
    )

    return RepoContext(
        repo_url=repo_url,
        workdir=str(workdir),
        current_branch=current,
        default_branch=default,
        remotes=remotes[:10],
        recent_commits=recent,
        dirty=bool(status),
        top_level=top_level,
        languages=languages,
        package_managers=pms,
        test_command=test_cmd,
        start_command=start_cmd,
        is_web=is_web,
        web_hints=web_hints,
        constraints_excerpt=_constraints_excerpt(workdir),
        stack_notes=stack_notes,
    )
