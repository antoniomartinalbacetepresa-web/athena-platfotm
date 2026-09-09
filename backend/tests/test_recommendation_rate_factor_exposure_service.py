from datetime import datetime, timedelta, timezone
import json
import math

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import MarketObservationRepository
from app.repositories.recommendation_macro_pit_observation_repository import (
    RecommendationMacroPitObservationRepository,
)
from app.repositories.recommendation_rate_factor_exposure_repository import (
    RecommendationRateFactorExposureRepository,
)
from app.services.recommendation_macro_pit_observation_service import (
    RecommendationMacroPitObservationService,
)
from app.services.recommendation_rate_factor_exposure_service import (
    RecommendationRateFactorExposureService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=20)
AS_OF = END + timedelta(days=2)


def build_service(tmp_path, *, days: int = 21):
    db = AthenaDatabase(tmp_path / "athena.db")
    market = MarketObservationRepository(db)
    macro = RecommendationMacroPitObservationRepository(database=db)
    macro_artifacts = RecommendationMacroPitObservationService()

    rates: list[float] = []
    rate = 4.0
    price = 100.0
    prices: list[dict[str, object]] = []
    for index in range(days):
        observed = START + timedelta(days=index)
        rate += 0.005 + 0.0005 * index
        rates.append(rate)
        if index > 0:
            rate_change = rates[index] - rates[index - 1]
            price *= 1.0 + 0.2 * rate_change
        prices.append({"observed_at": observed, "adjusted_close": price})
        macro.append(
            artifact=macro_artifacts.build_artifact(
                series_id="DGS10",
                value=rate,
                observed_at=observed,
                available_at=observed,
                source_provider="fred_alfred",
                source_ref=f"DGS10:{observed.date()}:v1",
                unit="percent",
            )
        )

    market.save_many(
        instrument_id=1,
        observations=prices,
        source_provider="yahoo",
        retrieved_at=AS_OF,
    )
    return RecommendationRateFactorExposureService(
        market_repository=market,
        macro_repository=macro,
    ), macro, db


def evaluate(service, *, end: datetime = END, as_of: datetime = AS_OF):
    return service.evaluate(
        instrument_id=1,
        market_source_provider="yahoo",
        rate_series_id="DGS10",
        period_start=START,
        period_end=end,
        as_of=as_of,
    )


def test_rates_exposure_uses_paired_pit_evidence_and_is_bounded(tmp_path) -> None:
    service, _, _ = build_service(tmp_path)
    artifact = evaluate(service)
    assert artifact["module"] == "pit_rate_factor_exposure"
    assert artifact["sampleCount"] == 20
    assert math.isclose(artifact["factors"]["rates"], 1.0, abs_tol=1e-9)
    assert len(artifact["factorExposureKey"]) == 64
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert artifact["policy"]["thresholds"] == "not_calibrated"
    assert all(len(item["macroObservationKey"]) == 64 for item in artifact["samples"])


def test_rates_exposure_ignores_revision_not_available_at_as_of(tmp_path) -> None:
    service, macro, _ = build_service(tmp_path)
    before = evaluate(service)
    macro_service = RecommendationMacroPitObservationService()
    macro.append(
        artifact=macro_service.build_artifact(
            series_id="DGS10",
            value=99.0,
            observed_at=START + timedelta(days=10),
            available_at=AS_OF + timedelta(days=1),
            source_provider="fred_alfred",
            source_ref="DGS10:revision:future",
            unit="percent",
        )
    )
    after = evaluate(service)
    assert before["factorExposureKey"] == after["factorExposureKey"]
    assert before["factors"] == after["factors"]


def test_rates_exposure_rejects_insufficient_sample(tmp_path) -> None:
    service, _, _ = build_service(tmp_path, days=20)
    with pytest.raises(ValueError, match="21 fechas"):
        service.evaluate(
            instrument_id=1,
            market_source_provider="yahoo",
            rate_series_id="DGS10",
            period_start=START,
            period_end=START + timedelta(days=19),
            as_of=AS_OF,
        )


def test_rates_exposure_rejects_fmp_and_future_period(tmp_path) -> None:
    service, _, _ = build_service(tmp_path)
    with pytest.raises(ValueError, match="FMP"):
        service.evaluate(
            instrument_id=1,
            market_source_provider="fmp",
            rate_series_id="DGS10",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="posterior a as_of"):
        evaluate(service, end=AS_OF + timedelta(days=1), as_of=AS_OF)


def test_rates_repository_is_idempotent_and_tamper_evident(tmp_path) -> None:
    service, _, db = build_service(tmp_path)
    artifact = evaluate(service)
    repository = RecommendationRateFactorExposureRepository(database=db, service=service)
    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    assert first["id"] == second["id"]

    with db.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_rate_factor_exposures WHERE id = ?",
            (first["id"],),
        ).fetchone()
        payload = json.loads(row["artifact_json"])
        payload["factors"]["rates"] = -0.5
        connection.execute(
            "UPDATE athena_rate_factor_exposures SET artifact_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), first["id"]),
        )

    with pytest.raises(ValueError, match="factorExposureKey"):
        repository.get_by_key(factor_exposure_key=str(first["factor_exposure_key"]))
