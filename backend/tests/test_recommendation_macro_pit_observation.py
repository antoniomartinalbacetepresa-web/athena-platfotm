from datetime import datetime, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_macro_pit_observation_repository import (
    RecommendationMacroPitObservationRepository,
)
from app.services.recommendation_macro_pit_observation_service import (
    RecommendationMacroPitObservationService,
)


UTC = timezone.utc
OBSERVED = datetime(2026, 1, 1, tzinfo=UTC)
AVAILABLE = datetime(2026, 1, 2, tzinfo=UTC)
AS_OF = datetime(2026, 1, 3, tzinfo=UTC)


def artifact(*, value: float = 4.25, available_at: datetime = AVAILABLE, source_ref: str = "DGS10:2026-01-01:v1") -> dict[str, object]:
    return RecommendationMacroPitObservationService().build_artifact(
        series_id="DGS10",
        value=value,
        observed_at=OBSERVED,
        available_at=available_at,
        source_provider="fred_alfred",
        source_ref=source_ref,
        unit="percent",
    )


def repository(tmp_path) -> RecommendationMacroPitObservationRepository:
    return RecommendationMacroPitObservationRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def test_macro_artifact_preserves_research_only_contract_and_identity() -> None:
    first = artifact()
    second = artifact()
    assert first["observationKey"] == second["observationKey"]
    assert len(str(first["observationKey"])) == 64
    assert first["advisoryStatus"] == "no_advice"
    assert first["productionEligible"] is False
    assert first["isWeightingReady"] is False
    assert first["policy"]["automaticTrading"] is False
    assert first["policy"]["revisionHandling"] == "vintages_preserved_never_backfilled_into_prior_as_of"


def test_macro_artifact_rejects_nonfinite_naive_time_and_fmp() -> None:
    service = RecommendationMacroPitObservationService()
    with pytest.raises(ValueError, match="finito"):
        service.build_artifact(
            series_id="DGS10", value=float("nan"), observed_at=OBSERVED,
            available_at=AVAILABLE, source_provider="fred_alfred", source_ref="x", unit="percent"
        )
    with pytest.raises(ValueError, match="zona horaria"):
        service.build_artifact(
            series_id="DGS10", value=4.0, observed_at=datetime(2026, 1, 1),
            available_at=AVAILABLE, source_provider="fred_alfred", source_ref="x", unit="percent"
        )
    with pytest.raises(ValueError, match="FMP"):
        service.build_artifact(
            series_id="DGS10", value=4.0, observed_at=OBSERVED,
            available_at=AVAILABLE, source_provider="fmp", source_ref="x", unit="percent"
        )


def test_macro_artifact_rejects_availability_before_observation() -> None:
    service = RecommendationMacroPitObservationService()
    with pytest.raises(ValueError, match="posterior"):
        service.build_artifact(
            series_id="DGS10",
            value=4.0,
            observed_at=AVAILABLE,
            available_at=OBSERVED,
            source_provider="fred_alfred",
            source_ref="x",
            unit="percent",
        )


def test_repository_is_idempotent_and_detects_provenance_conflict(tmp_path) -> None:
    repo = repository(tmp_path)
    first = repo.append(artifact=artifact())
    second = repo.append(artifact=artifact())
    assert first["id"] == second["id"]

    conflicting = artifact(value=4.50)
    # Force the same source identity while retaining the different canonical key.
    conflicting["sourceRef"] = "DGS10:2026-01-01:v1"
    service = RecommendationMacroPitObservationService()
    canonical_conflict = service.build_artifact(
        series_id="DGS10",
        value=4.50,
        observed_at=OBSERVED,
        available_at=AVAILABLE,
        source_provider="fred_alfred",
        source_ref="DGS10:2026-01-01:v1",
        unit="percent",
    )
    with pytest.raises(ValueError, match="provenance"):
        repo.append(artifact=canonical_conflict)


def test_repository_filters_revisions_by_information_available_at_as_of(tmp_path) -> None:
    repo = repository(tmp_path)
    first = artifact(value=4.25, source_ref="DGS10:2026-01-01:v1")
    revision_available = datetime(2026, 2, 1, tzinfo=UTC)
    revision = artifact(
        value=4.10,
        available_at=revision_available,
        source_ref="DGS10:2026-01-01:v2",
    )
    repo.append(artifact=first)
    repo.append(artifact=revision)

    early = repo.get_series_at_or_before(series_id="DGS10", as_of=AS_OF)
    late = repo.get_series_at_or_before(
        series_id="DGS10",
        as_of=datetime(2026, 2, 2, tzinfo=UTC),
    )
    assert [item["artifact"]["value"] for item in early] == [4.25]
    assert [item["artifact"]["value"] for item in late] == [4.25, 4.10]


def test_repository_detects_tampered_persisted_artifact(tmp_path) -> None:
    repo = repository(tmp_path)
    record = repo.append(artifact=artifact())
    db = AthenaDatabase(tmp_path / "athena.db")
    with db.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_macro_pit_observations WHERE id = ?",
            (record["id"],),
        ).fetchone()
        payload = json.loads(row["artifact_json"])
        payload["value"] = 9.99
        connection.execute(
            "UPDATE athena_macro_pit_observations SET artifact_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), record["id"]),
        )

    with pytest.raises(ValueError, match="observationKey"):
        repo.get_by_key(observation_key=str(record["observation_key"]))
