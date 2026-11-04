from datetime import datetime, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_performance_attribution_repository import (
    RecommendationPerformanceAttributionRepository,
)
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)


UTC = timezone.utc


def dt(day: int) -> datetime:
    return datetime(2026, 1, day, 12, tzinfo=UTC)


def _artifact() -> dict[str, object]:
    service = RecommendationPerformanceAttributionService()
    result = service.evaluate(
        as_of=dt(11),
        item=RecommendationPerformanceAttributionInput(
            instrument_id="101",
            symbol="AAA",
            instrument_currency="USD",
            reporting_currency="USD",
            fx_pair="USD/USD",
            benchmark_id="benchmark:SP500_TR",
            period_start=dt(1),
            period_end=dt(9),
            total_return=AttributionEvidence(0.08, dt(10), "sealed-return", "return:101:1"),
            market_contribution=AttributionEvidence(0.04, dt(10), "sealed-market", "market:101:1"),
            fx_contribution=AttributionEvidence(0.0, dt(10), "sealed-fx", "fx:101:1"),
            factor_contributions=(
                FactorContributionEvidence("quality", 0.01, dt(10), "sealed-factor", "quality:101:1"),
            ),
        ),
    )
    return result.to_api_dict()


def _repository(tmp_path) -> RecommendationPerformanceAttributionRepository:
    return RecommendationPerformanceAttributionRepository(
        database=AthenaDatabase(tmp_path / "athena-attribution.sqlite3")
    )


def test_append_read_and_identical_replay_are_idempotent(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    loaded = repository.get_by_key(attribution_key=str(artifact["attributionKey"]))

    assert first["id"] == second["id"] == loaded["id"]
    assert loaded["artifact"] == artifact
    assert len(loaded["artifact_hash"]) == 64
    assert loaded["artifact"]["policy"]["identityBinding"] == "numeric_values_plus_pit_provenance_plus_period_and_instrument"
    assert loaded["artifact"]["advisoryStatus"] == "no_advice"
    assert loaded["artifact"]["productionEligible"] is False
    assert loaded["artifact"]["isWeightingReady"] is False


def test_require_attribution_binds_exact_identity_period_currency_and_asof(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    record = repository.require_attribution(
        attribution_key=str(artifact["attributionKey"]),
        instrument_id="101",
        benchmark_id="benchmark:SP500_TR",
        reporting_currency="USD",
        period_start=dt(1),
        period_end=dt(9),
        as_of=dt(11),
    )
    assert record["artifact"]["attributionKey"] == artifact["attributionKey"]

    with pytest.raises(ValueError, match="instrumentId"):
        repository.require_attribution(
            attribution_key=str(artifact["attributionKey"]),
            instrument_id="202",
            benchmark_id="benchmark:SP500_TR",
            reporting_currency="USD",
            period_start=dt(1),
            period_end=dt(9),
            as_of=dt(11),
        )


def test_detects_json_tampering_even_if_numeric_result_remains_finite(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_performance_attribution_artifacts WHERE attribution_key = ?",
            (artifact["attributionKey"],),
        ).fetchone()
        body = json.loads(row["artifact_json"])
        body["totalReturn"] = 0.09
        connection.execute(
            "UPDATE athena_performance_attribution_artifacts SET artifact_json = ? WHERE attribution_key = ?",
            (json.dumps(body, sort_keys=True, separators=(",", ":")), artifact["attributionKey"]),
        )

    with pytest.raises(ValueError, match="reconstrucción|modificada"):
        repository.get_by_key(attribution_key=str(artifact["attributionKey"]))


def test_detects_indexed_column_tampering(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_performance_attribution_artifacts SET benchmark_id = 'other' WHERE attribution_key = ?",
            (artifact["attributionKey"],),
        )

    with pytest.raises(ValueError, match="benchmark_id"):
        repository.get_by_key(attribution_key=str(artifact["attributionKey"]))
