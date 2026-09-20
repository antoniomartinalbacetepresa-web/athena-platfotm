from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.canonical_weighting_governance import require_interactive_approval


_EVIDENCE_SHA = "a" * 64


def _proposal():
    return SimpleNamespace(evidence_sha256=_EVIDENCE_SHA)


def test_weighting_approval_is_blocked_for_noninteractive_callers() -> None:
    prompted = False

    def unexpected_prompt(_: str) -> str:
        nonlocal prompted
        prompted = True
        return _EVIDENCE_SHA

    with pytest.raises(RuntimeError, match="terminal humana interactiva"):
        require_interactive_approval(
            _proposal(),
            stdin_is_tty=False,
            input_fn=unexpected_prompt,
        )

    assert prompted is False


def test_weighting_approval_requires_exact_evidence_hash() -> None:
    with pytest.raises(RuntimeError, match="no coincide"):
        require_interactive_approval(
            _proposal(),
            stdin_is_tty=True,
            input_fn=lambda _: "b" * 64,
        )


def test_weighting_approval_accepts_interactive_exact_evidence_hash() -> None:
    require_interactive_approval(
        _proposal(),
        stdin_is_tty=True,
        input_fn=lambda _: f"  {_EVIDENCE_SHA.upper()}  ",
    )
