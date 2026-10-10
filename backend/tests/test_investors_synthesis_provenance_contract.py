from __future__ import annotations

import pytest

from app.api.recommendation_investors_synthesis import _provenance


HASH = "a" * 64
FINGERPRINT_A = "b" * 64
FINGERPRINT_B = "c" * 64


def _record() -> dict:
    return {
        "synthesis_hash": HASH,
        "package": {
            "synthesis": {
                "assessments": [
                    {
                        "evidenceId": "investors:2",
                        "assessmentFingerprint": FINGERPRINT_B,
                        "sourceRef": "https://example.com/filing-two",
                    },
                    {
                        "evidenceId": "investors:1",
                        "assessmentFingerprint": FINGERPRINT_A,
                        "sourceRef": "https://example.com/filing-one",
                    },
                ]
            }
        },
    }


def test_investors_provenance_exposes_deterministic_traceable_assessments() -> None:
    provenance = _provenance(_record())

    assert provenance == {
        "artifactHash": HASH,
        "artifactType": "canonical_investors_synthesis",
        "assessmentBindings": [
            {
                "evidenceId": "investors:1",
                "assessmentFingerprint": FINGERPRINT_A,
                "sourceRef": "https://example.com/filing-one",
            },
            {
                "evidenceId": "investors:2",
                "assessmentFingerprint": FINGERPRINT_B,
                "sourceRef": "https://example.com/filing-two",
            },
        ],
        "userFacingTraceability": True,
        "recommendationInfluence": False,
        "automaticScoring": False,
        "automaticTrading": False,
    }


@pytest.mark.parametrize("field", ["evidenceId", "assessmentFingerprint", "sourceRef"])
def test_investors_provenance_fails_closed_when_required_binding_is_missing(field: str) -> None:
    record = _record()
    del record["package"]["synthesis"]["assessments"][0][field]

    with pytest.raises(ValueError, match="provenance Investors canónica está incompleta"):
        _provenance(record)


def test_investors_provenance_rejects_non_hex_fingerprint_and_duplicate_evidence() -> None:
    malformed = _record()
    malformed["package"]["synthesis"]["assessments"][0]["assessmentFingerprint"] = "z" * 64
    with pytest.raises(ValueError, match="provenance Investors canónica está incompleta"):
        _provenance(malformed)

    duplicate = _record()
    duplicate["package"]["synthesis"]["assessments"][1]["evidenceId"] = "investors:2"
    with pytest.raises(ValueError, match="evidenceId duplicado"):
        _provenance(duplicate)


def test_investors_provenance_requires_non_empty_assessments() -> None:
    record = _record()
    record["package"]["synthesis"]["assessments"] = []

    with pytest.raises(ValueError, match="carece de assessments trazables"):
        _provenance(record)
