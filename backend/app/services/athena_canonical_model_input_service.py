from __future__ import annotations

from datetime import datetime

from app.services.recommendation_athena_synthesis_service import AthenaSynthesisModelInput


def canonical_athena_model_input(
    *,
    canonical_input_fingerprint: str,
    model_provider: str,
    model_name: str,
    model_version: str,
    generated_at: datetime,
    summary: str,
    rationale: str,
    uncertainties: tuple[str, ...],
    evidence_ids: tuple[str, ...],
) -> AthenaSynthesisModelInput:
    """Build the model boundary from the exact canonical API contract fingerprint.

    The caller must supply the already verified News/Investors/cycle fingerprint;
    this helper deliberately has no fallback to the legacy base fingerprint.
    """
    fingerprint = str(canonical_input_fingerprint or "").strip().lower()
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
        raise ValueError("canonical_input_fingerprint debe ser SHA-256 hexadecimal válido.")
    return AthenaSynthesisModelInput(
        model_provider=model_provider,
        model_name=model_name,
        model_version=model_version,
        input_fingerprint=fingerprint,
        generated_at=generated_at,
        summary=summary,
        rationale=rationale,
        uncertainties=uncertainties,
        evidence_ids=evidence_ids,
    )
