from datetime import datetime

from fastapi.testclient import TestClient

from app.api import recommendations
from app.main import app


class FakeTemporalSplitService:
    def __init__(self, *, advisory_status="no_advice", production_eligibility=False):
        self.calls = []
        self.advisory_status = advisory_status
        self.production_eligibility = production_eligibility

    def build(
        self,
        *,
        as_of: datetime,
        train_end: datetime,
        validation_end: datetime,
        horizon_days: int | None = None,
        require_benchmark: bool = True,
    ):
        self.calls.append(
            {
                "as_of": as_of,
                "train_end": train_end,
                "validation_end": validation_end,
                "horizon_days": horizon_days,
                "require_benchmark": require_benchmark,
            }
        )
        return {
            "status": "shadow_calibration_temporal_split",
            "counts": {"train": 10, "validation": 4, "test": 3, "purged": 2},
            "advisoryStatus": self.advisory_status,
            "policy": {
                "productionEligibility": self.production_eligibility,
                "split": "strict_chronological_no_shuffle",
            },
        }


def test_temporal_split_endpoint_forwards_boundaries_and_preserves_no_advice(
    monkeypatch,
) -> None:
    fake = FakeTemporalSplitService()
    monkeypatch.setattr(recommendations, "temporal_split_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-temporal-split",
        params={
            "trainEnd": "2026-04-01T00:00:00+00:00",
            "validationEnd": "2026-07-01T00:00:00+00:00",
            "as_of": "2026-10-01T00:00:00+00:00",
            "horizonDays": 30,
            "requireBenchmark": True,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["advisoryStatus"] == "no_advice"
    assert body["policy"]["productionEligibility"] is False
    assert body["counts"]["purged"] == 2
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["horizon_days"] == 30
    assert call["require_benchmark"] is True
    assert call["train_end"].utcoffset() is not None
    assert call["validation_end"].utcoffset() is not None
    assert call["as_of"].utcoffset() is not None


def test_temporal_split_endpoint_blocks_accidental_advice_contract(monkeypatch) -> None:
    fake = FakeTemporalSplitService(advisory_status="advice")
    monkeypatch.setattr(recommendations, "temporal_split_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-temporal-split",
        params={
            "trainEnd": "2026-04-01T00:00:00+00:00",
            "validationEnd": "2026-07-01T00:00:00+00:00",
            "as_of": "2026-10-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 500
    assert "no-advice" in response.json()["detail"]


def test_temporal_split_endpoint_blocks_production_eligibility(monkeypatch) -> None:
    fake = FakeTemporalSplitService(production_eligibility=True)
    monkeypatch.setattr(recommendations, "temporal_split_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-temporal-split",
        params={
            "trainEnd": "2026-04-01T00:00:00+00:00",
            "validationEnd": "2026-07-01T00:00:00+00:00",
            "as_of": "2026-10-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 500
    assert "no puede habilitar producción" in response.json()["detail"]


def test_temporal_split_endpoint_requires_boundary_timezone(monkeypatch) -> None:
    fake = FakeTemporalSplitService()
    monkeypatch.setattr(recommendations, "temporal_split_service", fake)
    client = TestClient(app)

    response = client.get(
        "/api/v1/recommendations/learning/shadow-temporal-split",
        params={
            "trainEnd": "2026-04-01T00:00:00",
            "validationEnd": "2026-07-01T00:00:00+00:00",
            "as_of": "2026-10-01T00:00:00+00:00",
        },
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]
