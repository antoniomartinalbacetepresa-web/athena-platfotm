from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.athena_canonical_model_input_service import canonical_athena_model_input


def _build(fingerprint: str):
    return canonical_athena_model_input(
        canonical_input_fingerprint=fingerprint,
        model_provider="external-model",
        model_name="athena-explainer",
        model_version="1",
        generated_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        summary="Resumen",
        rationale="Razonamiento",
        uncertainties=("Datos futuros desconocidos",),
        evidence_ids=("investors:1", "news:1"),
    )


def test_canonical_model_input_uses_exact_verified_contract_fingerprint() -> None:
    fingerprint = "a" * 64
    model_input = _build(fingerprint)

    assert model_input.input_fingerprint == fingerprint


def test_canonical_model_input_has_no_legacy_base_fingerprint_fallback() -> None:
    for malformed in ("", "a" * 63, "g" * 64):
        with pytest.raises(ValueError, match="SHA-256 hexadecimal válido"):
            _build(malformed)
