from __future__ import annotations

from datetime import datetime, timezone

from app.api.recommendation_athena_synthesis import _input_contract


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _cycle_record() -> dict:
    return {
        "cycle_hash": HASH_A,
        "radar_hash": HASH_B,
    }


def _contract() -> dict:
    return {
        "inputAsOf": datetime(2026, 9, 17, tzinfo=timezone.utc),
        "evidenceIds": ("investors:1",),
        "coveredCategories": ("investors",),
        "hasNews": False,
        "hasInvestors": True,
    }


def _investors_record(assessment_fingerprint: str) -> dict:
    return {
        "synthesis_hash": HASH_C,
        "package": {
            "synthesis": {
                "assessments": [
                    {
                        "evidenceId": "investors:1",
                        "assessmentFingerprint": assessment_fingerprint,
                        "sourceRef": "https://example.com/investors/1",
                    }
                ]
            }
        },
    }


def test_investors_assessment_mutation_changes_athena_canonical_input_fingerprint() -> None:
    before = _input_contract(
        _cycle_record(),
        None,
        _investors_record(HASH_D),
        _contract(),
    )
    after = _input_contract(
        _cycle_record(),
        None,
        _investors_record("e" * 64),
        _contract(),
    )

    assert before["investorsSynthesisHash"] == after["investorsSynthesisHash"] == HASH_C
    assert before["investorsProvenance"]["assessmentBindings"] != after["investorsProvenance"]["assessmentBindings"]
    assert before["inputFingerprint"] != after["inputFingerprint"]
    assert before["recommendationInfluence"] is False
    assert before["automaticTrading"] is False
