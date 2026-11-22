"""Read-only local toolchain preflight; never claims CI or deployment acceptance."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

EXPECTED_BRANCH = "dev/real-market-backend"


def probe(root: Path) -> dict:
    """Return structured diagnostics without installing tools or changing files."""
    result = {"schema": "athena.environment-preflight.v1", "branch": None,
              "branch_ok": False, "python": None, "flutter": None,
              "git": None, "backend_requirements": False,
              "flutter_manifest": False, "ready": False}
    for name in ("python", "flutter", "git"):
        # Linux Codespaces and CI commonly expose python3, not python.
        binary = (shutil.which("python3") or shutil.which("python")) if name == "python" else shutil.which(name)
        if not binary:
            continue
        try:
            completed = subprocess.run([binary, "--version"], cwd=root,
                                       capture_output=True, text=True,
                                       timeout=25, check=False)
            if completed.returncode == 0:
                lines = (completed.stdout or completed.stderr).strip().splitlines()
                version = lines[0] if lines else None
                # Fail closed: a Python 2 executable must never satisfy the Python 3 gate.
                if name == "python" and (not version or not re.match(r"^Python 3(?:\\.|$)", version)):
                    continue
                result[name] = version
        except (OSError, subprocess.TimeoutExpired):
            pass
    if result["git"]:
        try:
            completed = subprocess.run(["git", "branch", "--show-current"], cwd=root,
                                       capture_output=True, text=True, timeout=10,
                                       check=False)
            if completed.returncode == 0:
                result["branch"] = completed.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
    result["branch_ok"] = result["branch"] == EXPECTED_BRANCH
    result["backend_requirements"] = (root / "backend" / "requirements.txt").is_file()
    result["flutter_manifest"] = (root / "app" / "pubspec.yaml").is_file()
    result["ready"] = all((result["branch_ok"], result["python"], result["flutter"],
                           result["git"], result["backend_requirements"],
                           result["flutter_manifest"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ATHENA development environment check")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    outcome = probe(args.root.resolve())
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    return 0 if outcome["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
