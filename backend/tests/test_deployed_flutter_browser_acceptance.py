"""Configuration safety checks for the opt-in deployed browser runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "scripts" / "deployed_flutter_browser_acceptance.py"
spec = importlib.util.spec_from_file_location("deployed_flutter_browser_acceptance", PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
SHA = "a" * 40


def config(**changes):
    env = {
        "GITHUB_SHA": SHA,
        "ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA": SHA,
        "ATHENA_ACCEPTANCE_WEB_URL": "https://staging.example.test/",
    }
    env.update(changes)
    return module.validate_config(env)


def test_exact_sha_and_https_origin():
    result = config()
    assert result.base_url == "https://staging.example.test/"
    assert result.deployed_sha == SHA


@pytest.mark.parametrize("url", [
    "http://staging.example.test", "https://user:password@staging.example.test",
    "https://staging.example.test/private", "https://staging.example.test/?token=x",
    "https://staging.example.test/#secret",
])
def test_unsafe_web_origins_fail_closed(url):
    with pytest.raises(module.BrowserAcceptanceFailure):
        config(ATHENA_ACCEPTANCE_WEB_URL=url)


@pytest.mark.parametrize("sha", ["", "b" * 40, "not-a-sha"])
def test_missing_or_mismatched_sha_fails_closed(sha):
    with pytest.raises(module.BrowserAcceptanceFailure):
        config(ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA=sha)


def test_missing_config_never_logs_secrets(monkeypatch, capsys):
    monkeypatch.delenv("ATHENA_ACCEPTANCE_WEB_URL", raising=False)
    monkeypatch.setenv("ATHENA_ACCEPTANCE_DEPLOYED_WEB_SHA", "secret-not-to-log")
    assert module.main() == 2
    assert "secret-not-to-log" not in capsys.readouterr().out
