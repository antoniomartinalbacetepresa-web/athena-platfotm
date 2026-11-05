"""Read-only local/VPS resource preflight for ATHENA TYCHE.

No credentials, orders, network calls, or third-party dependencies.
Run: python -m scripts.runtime_resource_preflight --json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys


def collect_resources(*, storage_path: str | Path = ".", memory_bytes: int | None = None,
                      cpu_count: int | None = None) -> dict:
    """Return observable capacity and conservative readiness, not a production guarantee."""
    path = Path(storage_path).resolve()
    disk = shutil.disk_usage(path)
    cpu = cpu_count if cpu_count is not None else os.cpu_count()
    memory = memory_bytes if memory_bytes is not None else _physical_memory_bytes()
    warnings = []
    if cpu is None:
        warnings.append("cpu_capacity_unknown")
    elif cpu < 2:
        warnings.append("limited_cpu_capacity")
    if memory is None:
        warnings.append("memory_capacity_unknown")
    elif memory < 4 * 1024 ** 3:
        warnings.append("limited_memory_capacity")
    if disk.free < 10 * 1024 ** 3:
        warnings.append("limited_free_disk")
    return {
        "platform": sys.platform,
        "logicalCpuCount": cpu,
        "physicalMemoryBytes": memory,
        "diskFreeBytes": disk.free,
        "diskTotalBytes": disk.total,
        "storagePath": str(path),
        "warnings": warnings,
        "productionReady": False,
        "tradingEnabled": False,
        "note": "Capacity preflight only; security, stability, broker and data licensing remain unverified.",
    }


def _physical_memory_bytes() -> int | None:
    if sys.platform == "win32":
        try:
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memoryLoad", ctypes.c_ulong),
                            ("totalPhys", ctypes.c_ulonglong), ("availPhys", ctypes.c_ulonglong),
                            ("totalPageFile", ctypes.c_ulonglong), ("availPageFile", ctypes.c_ulonglong),
                            ("totalVirtual", ctypes.c_ulonglong), ("availVirtual", ctypes.c_ulonglong),
                            ("availExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.totalPhys)
        except (AttributeError, OSError, ValueError):
            return None
    elif sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-path", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = collect_resources(storage_path=args.storage_path)
    except OSError as exc:
        parser.error(f"Cannot inspect storage path: {exc}")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
