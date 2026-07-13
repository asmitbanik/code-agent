"""Persist contribute run state across issues."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ContributeState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {"issues": {}}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {"issues": {}}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get_issue(self, number: int) -> dict[str, Any]:
        return dict(self.data.setdefault("issues", {}).get(str(number) or {}, {}))

    def set_issue(self, number: int, **kwargs: Any) -> None:
        issues = self.data.setdefault("issues", {})
        cur = dict(issues.get(str(number)) or {})
        cur.update(kwargs)
        issues[str(number)] = cur
        self.save()

    def already_done(self, number: int) -> bool:
        cur = self.get_issue(number)
        return cur.get("status") in {"pr_opened", "ci_passed", "skipped"}
