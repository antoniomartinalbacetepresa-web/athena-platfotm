from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_market_beta_exposure_service import RecommendationMarketBetaExposureService


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=20)
AS_OF = END + timedelta(days=1)


class FakeRepository:
    def __init__(self, *, late: bool = False) -> None:
        self.late = late

    def list_for_instrument(self, instrument_id: int, **kwargs: object):
        price = 100.0
        rows = []
        for index in range(21):
            observed = START + timedelta(days=index)
            if index:
                market_return = 0.005 + 0.001 * (index % 7)
                factor = 2.0 if instrument_id == 1 else 1.0
                price *= 1.0 + factor * market_return
            retrieved = observed if not self.late else AS_OF + timedelta(days=1)
            rows.append(
                {
                    "observed_at": observed.isoformat(),
                    "adjusted_close": price,
                    "close": price,
                    "retrieved_at": retrieved.isoformat(),
                }
            )
        return rows


def test_market_beta_is_derived_from_paired_pit_returns() -> None:
    service = RecommendationMarketBetaExposureService(FakeRepository())
    artifact = service.evaluate(
        instrument_id=1,
        benchmark_instrument_id=2,
        source_provider="test-provider",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert artifact["sampleCount"] == 20
    assert artifact["factors"]["market"] == pytest.approx(2.0, abs=1e-10)
    assert len(artifact["factorExposureKey"]) == 64
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert artifact["policy"]["missingFactors"] == "not_inferred"


def test_market_beta_identity_is_provenance_bound() -> None:
    first = RecommendationMarketBetaExposureService(FakeRepository()).evaluate(
        instrument_id=1,
        benchmark_instrument_id=2,
        source_provider="provider-a",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    second = RecommendationMarketBetaExposureService(FakeRepository()).evaluate(
        instrument_id=1,
        benchmark_instrument_id=2,
        source_provider="provider-b",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert first["factorExposureKey"] != second["factorExposureKey"]


def test_market_beta_fails_closed_on_late_knowledge() -> None:
    service = RecommendationMarketBetaExposureService(FakeRepository(late=True))
    with pytest.raises((ValueError, RuntimeError), match="PIT|posterior|retrieved"):
        service.evaluate(
            instrument_id=1,
            benchmark_instrument_id=2,
            source_provider="test-provider",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )


def test_market_beta_tampering_breaks_identity() -> None:
    service = RecommendationMarketBetaExposureService(FakeRepository())
    artifact = service.evaluate(
        instrument_id=1,
        benchmark_instrument_id=2,
        source_provider="test-provider",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    artifact["factors"]["market"] = 3.0
    with pytest.raises(ValueError, match="factorExposureKey"):
        service.validate_artifact(artifact)
