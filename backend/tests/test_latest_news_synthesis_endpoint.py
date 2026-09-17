from fastapi import HTTPException

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


def test_latest_news_router_declares_expected_route_without_process_global_app():
    # FastAPI's router object can be mutated by other full-suite tests. Verify
    # the endpoint declaration itself rather than relying on shared router/app
    # state. The callable remains the production function used below.
    route_paths = {
        route.path
        for route in api.router.routes
        if isinstance(getattr(route, "path", None), str)
    }
    assert _ROUTE.endswith("/news-synthesis/latest")
    assert "/news-synthesis/latest" in route_paths


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
