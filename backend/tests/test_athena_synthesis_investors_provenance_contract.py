from __future__ import annotations

import pytest

from app.api.recommendation_athena_synthesis import (
    _input_contract,
    _investors_provenance_binding,
    _response_provenance,
)


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
                        "sourceRef": "https://example.com/two",
                    },
                    {
                        "evidenceId": "investors:1",
                        "assessmentFingerprint": FINGERPRINT_A,
                        "sourceRef": "https://example.com/one",
                    },
                ]
            }
        },
    }


def test_athena_investors_binding_reuses_canonical_investors_provenance() -> None:
    binding = _investors_provenance_binding(_record())

    assert binding == {
        "artifactHash": HASH,
        "artifactType": "canonical_investors_synthesis",
        "assessmentBindings": [
            {
                "evidenceId": "investors:1",
                "assessmentFingerprint": FINGERPRINT_A,
                "sourceRef": "https://example.com/one",
            },
            {
                "evidenceId": "investors:2",
                "assessmentFingerprint": FINGERPRINT_B,
                "sourceRef": "https://example.com/two",
            },
        ],
        "userFacingTraceability": True,
        "recommendationInfluence": False,
        "automaticScoring": False,
        "automaticTrading": False,
    }


def test_athena_investors_binding_fails_closed_with_invalid_provenance() -> None:
    invalid = _record()
    invalid["package"]["synthesis"]["assessments"][0]["assessmentFingerprint"] = "z" * 64

    with pytest.raises(ValueError, match="provenance Investors canónica está incompleta"):
        _investors_provenance_binding(invalid)


def test_athena_response_provenance_exposes_news_and_investors_symmetrically() -> None:
    contract = {
        "newsProvenance": {"artifactType": "canonical_news_synthesis"},
        "investorsProvenance": {"artifactType": "canonical_investors_synthesis"},
    }

    provenance = _response_provenance(contract, "d" * 64)

    assert provenance["news"]["artifactType"] == "canonical_news_synthesis"
    assert provenance["investors"]["artifactType"] == "canonical_investors_synthesis"
    assert provenance["inputFingerprint"] == "d" * 64


def test_absent_investors_dependency_has_no_fabricated_provenance() -> None:
    assert _investors_provenance_binding(None) is None
    assert "investors" not in _response_provenance({}, "e" * 64)
