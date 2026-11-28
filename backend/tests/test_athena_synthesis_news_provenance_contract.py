from __future__ import annotations

import pytest

from app.api.recommendation_athena_synthesis import _news_provenance_binding


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
                        "evidenceId": "news:2",
                        "assessmentFingerprint": FINGERPRINT_B,
                        "sourceRef": "https://example.com/two",
                    },
                    {
                        "evidenceId": "news:1",
                        "assessmentFingerprint": FINGERPRINT_A,
                        "sourceRef": "https://example.com/one",
                    },
                ]
            }
        },
    }


def test_news_provenance_binding_exposes_traceable_canonical_assessments() -> None:
    binding = _news_provenance_binding(_record())

    assert binding == {
        "artifactHash": HASH,
        "artifactType": "canonical_news_synthesis",
        "assessmentBindings": [
            {
                "evidenceId": "news:1",
                "assessmentFingerprint": FINGERPRINT_A,
                "sourceRef": "https://example.com/one",
            },
            {
                "evidenceId": "news:2",
                "assessmentFingerprint": FINGERPRINT_B,
                "sourceRef": "https://example.com/two",
            },
        ],
        "userFacingTraceability": True,
        "recommendationInfluence": False,
        "automaticTrading": False,
    }


def test_news_provenance_binding_fails_closed_on_missing_or_duplicate_evidence() -> None:
    missing = _record()
    del missing["package"]["synthesis"]["assessments"][0]["sourceRef"]
    with pytest.raises(ValueError, match="provenance News canónica está incompleta"):
        _news_provenance_binding(missing)

    duplicate = _record()
    duplicate["package"]["synthesis"]["assessments"][1]["evidenceId"] = "news:2"
    with pytest.raises(ValueError, match="evidenceId duplicado"):
        _news_provenance_binding(duplicate)


def test_absent_news_dependency_has_no_fabricated_provenance() -> None:
    assert _news_provenance_binding(None) is None
