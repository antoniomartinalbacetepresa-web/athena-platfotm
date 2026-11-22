"""Isolated tests of read-only environment checks."""
from pathlib import Path
from unittest.mock import patch
import subprocess

from scripts.environment_preflight import probe


def test_missing_tools_fail_closed(tmp_path: Path):
    with patch("scripts.environment_preflight.shutil.which", return_value=None):
        result = probe(tmp_path)
    assert result["ready"] is False
    assert result["branch_ok"] is False
    assert result["flutter"] is None


def test_toolchain_and_branch_ready(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("pytest\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pubspec.yaml").write_text("name: app\n")
    def run(command, **kwargs):
        if command[1:] == ["branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, "dev/real-market-backend\n", "")
        return subprocess.CompletedProcess(command, 0, "version 1\n", "")
    with patch("scripts.environment_preflight.shutil.which", side_effect=lambda n: "/bin/" + n), patch("scripts.environment_preflight.subprocess.run", side_effect=run):
        result = probe(tmp_path)
    assert result["ready"] is True
    assert result["branch_ok"] is True


def test_wrong_branch_blocks_ready(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").touch()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pubspec.yaml").touch()
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "main\n" if "branch" in command else "version\n", "")
    with patch("scripts.environment_preflight.shutil.which", side_effect=lambda n: "/bin/" + n), patch("scripts.environment_preflight.subprocess.run", side_effect=run):
        result = probe(tmp_path)
    assert result["ready"] is False
    assert result["branch"] == "main"
