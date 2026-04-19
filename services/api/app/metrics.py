"""Сбор метрик хоста. Контейнер видит лимиты cgroup — для «честных» данных проще network_mode: host для api (опционально)."""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import psutil


def _vcgencmd_temp_c() -> float | None:
    """Как в prev/fan_control.py — на Raspberry Pi OS / Ubuntu для Pi обычно есть vcgencmd."""
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=2)
        return float(out.replace("temp=", "").strip().rstrip("'C"))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def _read_pi_temp_c() -> float | None:
    path = os.getenv("CPU_TEMP_SYSFS", "/sys/class/thermal/thermal_zone0/temp")
    try:
        with open(path, encoding="utf-8") as f:
            raw = int(f.read().strip())
        # milli-Celsius на большинстве Pi
        return raw / 1000.0 if raw > 1000 else float(raw)
    except OSError:
        return None


def _uptime_human() -> str:
    boot = psutil.boot_time()
    sec = int(time.time() - boot)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:d}ч {m:02d}м {s:02d}с"


def collect_status() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    temp = _vcgencmd_temp_c()
    if temp is None:
        temp = _read_pi_temp_c()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "mem_percent": vm.percent,
        "disk_percent": disk.percent,
        "load_avg": list(load),
        "cpu_temp_c": temp,
        "uptime_human": _uptime_human(),
    }
