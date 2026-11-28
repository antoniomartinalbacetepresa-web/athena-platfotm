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
    limit = _linux_cgroup_memory_limit() if sys.platform.startswith("linux") else None
    effective_memory = min(memory, limit) if memory is not None and limit is not None else (limit if memory is None else memory)
    warnings = []
    if limit is not None and (memory is None or limit < memory):
        warnings.append("container_memory_limited")
    if cpu is None:
        warnings.append("cpu_capacity_unknown")
    elif cpu < 2:
        warnings.append("limited_cpu_capacity")
    if effective_memory is None:
        warnings.append("memory_capacity_unknown")
    elif effective_memory < 4 * 1024 ** 3:
        warnings.append("limited_memory_capacity")
    if disk.free < 10 * 1024 ** 3:
        warnings.append("limited_free_disk")
    return {
        "platform": sys.platform,
        "logicalCpuCount": cpu,
        "physicalMemoryBytes": memory,
        "effectiveMemoryBytes": effective_memory,
        "containerMemoryLimitBytes": limit,
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



def _linux_cgroup_memory_limit() -> int | None:
    """Read common Linux cgroup limits; 'max' and huge v1 sentinels mean unlimited."""
    for filename in ("/sys/fs/cgroup/memory.max",
                     "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = Path(filename).read_text(encoding="ascii").strip()
            if value == "max":
                continue
            limit = int(value)
            if 0 < limit < 1 << 60:
                return limit
        except (OSError, ValueError):
            continue
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
