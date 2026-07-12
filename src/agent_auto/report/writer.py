"""Write run reports and live logs."""

from __future__ import annotations

import json
from pathlib import Path

from agent_auto.models import RunReport, utc_now


class ReportWriter:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "artifacts").mkdir(exist_ok=True)
        self.log_path = self.run_dir / "agent.log"
        self.report_path = self.run_dir / "report.json"

    def log(self, message: str) -> None:
        line = message.rstrip() + "\n"
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def save(self, report: RunReport) -> Path:
        payload = report.model_dump(mode="json")
        self.report_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return self.report_path

    def finish(self, report: RunReport) -> Path:
        report.finished_at = utc_now()
        return self.save(report)
