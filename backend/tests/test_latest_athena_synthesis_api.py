from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import recommendation_latest_athena_synthesis as api
from app.main import app


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def test_latest_athena_route_is_registered() -> None:
    response = TestClient(app).get(
        "/api/v1/recommendations/professional-research/athena-synthesis/latest"
    )
    assert response.status_code == 404


def test_latest_athena_rejects_stale_canonical_fingerprint(monkeypatch) -> None:
    record = {
        "cycle_hash": HASH_A,
        "radar_hash": HASH_B,
        "news_synthesis_hash": None,
        "package": {
            "synthesis": {
                "inputFingerprint": HASH_C,
                "recommendationInfluence": False,
                "automaticTrading": False,
            }
        },
    }
    cycle = {"cycle_hash": HASH_A, "radar_hash": HASH_B}
    contract = {
        "inputAsOf": datetime(2026, 9, 17, tzinfo=timezone.utc),
        "evidenceIds": ("technical:1",),
        "coveredCategories": ("technical",),
        "hasNews": False,
        "hasInvestors": False,
    }

    monkeypatch.setattr(api.latest_repository, "get_latest", lambda: record)
    monkeypatch.setattr(api, "_dependencies", lambda cycle_hash: (cycle, None, None, contract))
    monkeypatch.setattr(
        api,
        "_input_contract",
        lambda *args: {"inputFingerprint": "d" * 64},
    )

    with pytest.raises(HTTPException) as exc_info:
        api.get_latest_athena_synthesis()

    assert exc_info.value.status_code == 404
    assert "obsoleta" in exc_info.value.detail


def test_latest_athena_exposes_only_revalidated_presentation_selection(monkeypatch) -> None:
    record = {
        "cycle_hash": HASH_A,
        "radar_hash": HASH_B,
        "news_synthesis_hash": None,
        "package": {
            "synthesis": {
                "inputFingerprint": HASH_C,
                "summary": "Verified research synthesis.",
                "recommendationInfluence": False,
                "automaticTrading": False,
            }
        },
    }
    cycle = {"cycle_hash": HASH_A, "radar_hash": HASH_B}
    contract = {
        "inputAsOf": datetime(2026, 9, 17, tzinfo=timezone.utc),
        "evidenceIds": ("technical:1",),
        "coveredCategories": ("technical",),
        "hasNews": False,
        "hasInvestors": False,
    }

    monkeypatch.setattr(api.latest_repository, "get_latest", lambda: record)
    monkeypatch.setattr(api, "_dependencies", lambda cycle_hash: (cycle, None, None, contract))
    monkeypatch.setattr(api, "_input_contract", lambda *args: {"inputFingerprint": HASH_C})

    result = api.get_latest_athena_synthesis()["data"]

    assert result["artifactBindingVerified"] is True
    assert result["cycleHash"] == HASH_A
    assert result["provenance"]["inputFingerprint"] == HASH_C
    assert result["selection"] == {
        "policy": "latest_persisted_then_canonical_revalidation",
        "presentationOnly": True,
        "recommendationInfluence": False,
        "automaticTrading": False,
    }
