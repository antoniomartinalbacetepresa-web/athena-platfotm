from fastapi import FastAPI, HTTPException

from app.api import recommendation_latest_news_synthesis as api


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_ROUTE = "/api/v1/recommendations/professional-research/news-synthesis/latest"


def _record(*, radar_hash: str = _HASH_B):
    return {
        "cycle_hash": _HASH_A,
        "radar_hash": radar_hash,
        "synthesis_hash": _HASH_C,
        "created_at": "2026-09-17T14:00:00+00:00",
        "package": {
            "synthesis": {
                "status": "validated_external_model_output",
                "assessedCount": 1,
                "includedCount": 1,
                "excludedCount": 0,
                "assessments": [{"evidenceId": "news-1"}],
                "items": [{"evidenceId": "news-1"}],
            }
        },
    }


def test_latest_news_router_registers_expected_route_in_isolation():
    # Do not inspect the process-global app here: other full-suite tests may
    # intentionally rebuild its router.  Prove that this router contributes the
    # exact production path when FastAPI includes it.
    isolated = FastAPI()
    isolated.include_router(api.router)
    paths = {
        route.path
        for route in isolated.routes
        if isinstance(getattr(route, "path", None), str)
    }
    assert _ROUTE in paths


def test_latest_news_revalidates_current_cycle_and_preserves_no_authority(monkeypatch):
    record = _record()
    monkeypatch.setattr(api.synthesis_repository, "get_latest", lambda: record)
    monkeypatch.setattr(api.synthesis_repository, "get_by_cycle_hash", lambda *, cycle_hash: record)
    monkeypatch.setattr(api.cycle_repository, "get_by_hash", lambda *, cycle_hash: {"cycle_hash": cycle_hash, "radar_hash": _HASH_B})
    monkeypatch.setattr(api, "_radar_from_cycle_record", lambda cycle: object())

    response = api.get_latest_news_synthesis()["data"]

    assert response["cycleBindingVerified"] is True
    assert response["presentationOnly"] is True
    assert response["recommendationInfluence"] is False
    assert response["automaticScoring"] is False
    assert response["automaticTrading"] is False
    assert response["persistence"]["packageIntegrityVerified"] is True


def test_latest_news_rejects_stale_radar_binding(monkeypatch):
    record = _record(radar_hash=_HASH_C)
    monkeypatch.setattr(api.synthesis_repository, "get_latest", lambda: record)
    monkeypatch.setattr(api.cycle_repository, "get_by_hash", lambda *, cycle_hash: {"cycle_hash": cycle_hash, "radar_hash": _HASH_B})
    monkeypatch.setattr(api, "_radar_from_cycle_record", lambda cycle: object())

    try:
        api.get_latest_news_synthesis()
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "radarHash" in str(exc.detail)
    else:
        raise AssertionError("Una síntesis News obsoleta debe fallar cerrada.")
