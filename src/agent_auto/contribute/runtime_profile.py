"""Detect laptop-compatible runtime capabilities for local verification."""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field


@dataclass
class RuntimeProfile:
    os_name: str
    ram_gb: float | None
    cpu_count: int
    has_docker: bool
    has_node: bool
    has_python: bool
    has_gpu: bool
    notes: list[str] = field(default_factory=list)

    @property
    def allow_heavy_services(self) -> bool:
        if self.ram_gb is not None and self.ram_gb < 6:
            return False
        return True


def _ram_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:  # noqa: BLE001
        pass
    # Windows fallback via env is unreliable; try ctypes
    try:
        if platform.system() == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullTotalPhys / (1024**3), 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def detect_runtime_profile() -> RuntimeProfile:
    notes: list[str] = []
    ram = _ram_gb()
    has_docker = shutil.which("docker") is not None
    if has_docker:
        # docker may be installed but daemon down
        import subprocess

        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0:
            has_docker = False
            notes.append("Docker CLI present but daemon unavailable; skipping containers")
    else:
        notes.append("Docker not available; prefer local node/python servers")

    profile = RuntimeProfile(
        os_name=platform.system(),
        ram_gb=ram,
        cpu_count=os.cpu_count() or 2,
        has_docker=has_docker,
        has_node=shutil.which("node") is not None,
        has_python=True,
        has_gpu=False,
        notes=notes,
    )
    if ram is not None and ram < 6:
        profile.notes.append(f"Low RAM ({ram}GB): skip heavy multi-service stacks")
    return profile
