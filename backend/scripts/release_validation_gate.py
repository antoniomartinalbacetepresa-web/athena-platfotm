"""Fail-closed CI release gate; deployed jobs are evidence only when run.

The protected staging browser owner journey must never be accepted without
its independent deployed API isolation gate. PR checks do not imply deployment.
"""
from __future__ import annotations

import os
from typing import Mapping


class ReleaseGateFailure(ValueError):
    """A safe CI gate failure without configuration values or secrets."""


def _enabled(environment: Mapping[str, str], name: str) -> bool:
    value = environment.get(name, "")
    if value not in ("", "false", "true"):
        raise ReleaseGateFailure(f"Invalid {name} setting")
    return value == "true"


def check_release_gate(environment: Mapping[str, str]) -> None:
    """Require core CI and enforce complete opt-in deployment dependencies."""
    if environment.get("BACKEND_RESULT") != "success":
        raise ReleaseGateFailure("Backend tests did not pass")
    if environment.get("FLUTTER_RESULT") != "success":
        raise ReleaseGateFailure("Flutter validation did not pass")

    deployed = _enabled(environment, "DEPLOYED_ENABLED")
    browser = _enabled(environment, "BROWSER_ENABLED")
    owner = _enabled(environment, "OWNER_BROWSER_ENABLED")
    if owner and (not deployed or not browser):
        raise ReleaseGateFailure(
            "Two-owner browser acceptance requires deployed API and guest browser gates"
        )

    event = environment.get("GITHUB_EVENT_NAME")
    if event not in ("push", "pull_request"):
        raise ReleaseGateFailure("Unsupported release validation event")
    if event == "pull_request":
        # No deployed job is run for PR events. A PR success is not staging proof.
        return
    if environment.get("GITHUB_REF") != "refs/heads/dev/real-market-backend":
        raise ReleaseGateFailure("Release gate requires the authorized development branch")
    if deployed and environment.get("DEPLOYED_RESULT") != "success":
        raise ReleaseGateFailure("Deployed API isolation acceptance did not pass")
    if browser and environment.get("BROWSER_RESULT") != "success":
        raise ReleaseGateFailure("Deployed browser acceptance did not pass")


def main() -> int:
    try:
        check_release_gate(os.environ)
    except ReleaseGateFailure as exc:
        print(f"Release validation gate blocked: {exc}")
        return 1
    print("Release validation gate passed (opt-in deployed jobs counted only when enabled).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
