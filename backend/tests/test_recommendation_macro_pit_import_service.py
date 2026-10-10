from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_macro_pit_observation_repository import (
    RecommendationMacroPitObservationRepository,
)
from app.services.recommendation_macro_pit_import_service import (
    RecommendationMacroPitImportService,
)


UTC = timezone.utc


def service(tmp_path) -> RecommendationMacroPitImportService:
    return RecommendationMacroPitImportService(
        repository=RecommendationMacroPitObservationRepository(
            database=AthenaDatabase(tmp_path / "athena.db")
        )
    )


def payload() -> dict[str, object]:
    return {
        "observations": [
            {
                "realtime_start": "2026-01-02",
                "realtime_end": "2026-01-31",
                "date": "2026-01-01",
                "value": "4.25",
            },
            {
                "realtime_start": "2026-01-02",
                "realtime_end": "2026-01-31",
                "date": "2026-01-02",
                "value": ".",
            },
        ]
    }


def test_import_uses_alfred_realtime_start_as_available_at(tmp_path) -> None:
    result = service(tmp_path).import_fred_alfred_payload(
        series_id="DGS10",
        payload=payload(),
        as_of=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert result["importedCount"] == 1
    assert result["skippedMissingCount"] == 1
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["policy"]["automaticTrading"] is False
    assert result["policy"]["vintageTimestamp"] == "realtime_start_used_as_available_at"


def test_import_rejects_future_vintage(tmp_path) -> None:
    future = payload()
    future["observations"][0]["realtime_start"] = "2026-02-01"
    with pytest.raises(ValueError, match="posterior al as_of"):
        service(tmp_path).import_fred_alfred_payload(
            series_id="DGS10",
            payload=future,
            as_of=datetime(2026, 1, 3, tzinfo=UTC),
        )


def test_import_rejects_naive_as_of(tmp_path) -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        service(tmp_path).import_fred_alfred_payload(
            series_id="DGS10",
            payload=payload(),
            as_of=datetime(2026, 1, 3),
        )


def test_import_is_idempotent_for_same_vintage(tmp_path) -> None:
    instance = service(tmp_path)
    first = instance.import_fred_alfred_payload(
        series_id="DGS10",
        payload=payload(),
        as_of=datetime(2026, 1, 3, tzinfo=UTC),
    )
    second = instance.import_fred_alfred_payload(
        series_id="DGS10",
        payload=payload(),
        as_of=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert first["observationKeys"] == second["observationKeys"]
