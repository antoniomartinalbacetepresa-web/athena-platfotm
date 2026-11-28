from datetime import datetime, timezone

from app.database.athena_database import AthenaDatabase
from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.repositories.normalized_data_repository import NormalizedDataRepository
from app.services.recommendation_macro_evidence_service import (
    RecommendationMacroEvidenceService,
)


AS_OF = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _save_macro(
    database: AthenaDatabase,
    *,
    value: object = 3.2,
    retrieved_at: str = "2026-09-02T10:00:00+00:00",
    available_at: str = "2026-09-01T12:00:00+00:00",
    metric: str = "macro.us.cpi_yoy",
) -> None:
    NormalizedDataRepository(database).save(
        NormalizedDatum(
            metric=metric,
            value=value,
            data_kind="fact",
            provenance=DataProvenance(
                source_id="fred_alfred",
                retrieved_at=retrieved_at,
                effective_at="2026-08-01",
                published_at="2026-09-01",
                available_at=available_at,
                version="vintage-2026-09-01",
                raw_identifier="CPIAUCSL",
                normalized_identifier=metric,
                source_url="https://fred.stlouisfed.org/series/CPIAUCSL",
            ),
            unit="percent",
            entity_id="country:US",
            quality_score=100.0,
            confidence_score=100.0,
        )
    )


def test_macro_evidence_is_fail_closed_when_no_pit_data_exists(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="aapl",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "no_data"
    assert payload["symbol"] == "AAPL"
    assert payload["observationCount"] == 0
    assert payload["observations"] == []
    assert payload["productionEligible"] is False
    assert payload["policy"]["directLiveApiReplayForbidden"] is True
    assert payload["policy"]["directionalScoreAssigned"] is False


def test_macro_evidence_exposes_persisted_pit_provenance_without_score(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _save_macro(database)

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "diagnostic_ready"
    assert payload["observationCount"] == 1
    observation = payload["observations"][0]
    assert observation["metric"] == "macro.us.cpi_yoy"
    assert observation["value"] == 3.2
    assert observation["sourceId"] == "fred_alfred"
    assert observation["availableAt"] == "2026-09-01T12:00:00+00:00"
    assert observation["retrievedAt"] == "2026-09-02T10:00:00+00:00"
    assert payload["policy"]["thresholdCalibrated"] is False
    assert payload["productionEligible"] is False


def test_macro_evidence_does_not_replay_data_retrieved_after_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _save_macro(
        database,
        retrieved_at="2026-09-04T10:00:00+00:00",
        available_at="2026-09-01T12:00:00+00:00",
    )

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "no_data"
    assert payload["observationCount"] == 0


def test_macro_evidence_does_not_replay_data_available_after_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _save_macro(
        database,
        retrieved_at="2026-09-02T10:00:00+00:00",
        available_at="2026-09-04T12:00:00+00:00",
    )

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "no_data"
    assert payload["observationCount"] == 0


def test_macro_evidence_rejects_non_finite_values(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _save_macro(database, value=float("inf"))

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "invalid_evidence"
    assert payload["observationCount"] == 0
    assert payload["productionEligible"] is False


def test_macro_evidence_rejects_boolean_values(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _save_macro(database, value=True)

    payload = RecommendationMacroEvidenceService(database).evaluate(
        symbol="AAPL",
        as_of=AS_OF,
    ).to_api_dict()

    assert payload["status"] == "invalid_evidence"
    assert payload["observationCount"] == 0
    assert payload["productionEligible"] is False


def test_macro_evidence_requires_timezone_aware_cutoff(tmp_path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    service = RecommendationMacroEvidenceService(database)

    try:
        service.evaluate(symbol="AAPL", as_of=datetime(2026, 9, 3, 12, 0))
    except ValueError as exc:
        assert "zona horaria" in str(exc)
    else:
        raise AssertionError("Expected timezone-naive as_of to fail closed")
