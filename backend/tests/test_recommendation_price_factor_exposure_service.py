from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_price_factor_exposure_service import (
    RecommendationPriceFactorExposureService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=20)
AS_OF = END + timedelta(days=1)


class FakeRepository:
    def __init__(self, *, late: bool = False, multiplier: float = 1.0) -> None:
        self.late = late
        self.multiplier = multiplier

    def list_for_instrument(self, instrument_id: int, **kwargs: object):
        price = 100.0
        rows = []
        for index in range(21):
            observed = START + timedelta(days=index)
            if index:
                price *= 1.0 + self.multiplier * (0.002 + 0.001 * (index % 5))
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


def evaluate(service: RecommendationPriceFactorExposureService, provider: str = "test-provider"):
    return service.evaluate(
        instrument_id=1,
        source_provider=provider,
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )


def test_price_factors_are_derived_from_pit_prices() -> None:
    artifact = evaluate(RecommendationPriceFactorExposureService(FakeRepository()))
    assert artifact["sampleCount"] == 20
    assert artifact["factors"]["momentum"] > 0.0
    assert artifact["factors"]["low_volatility"] <= 0.0
    assert artifact["diagnostics"]["realizedVolatilityUnannualized"] >= 0.0
    assert len(artifact["factorExposureKey"]) == 64
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["policy"]["automaticTrading"] is False
    assert artifact["policy"]["frequencyNormalization"] == "not_assumed"
    assert artifact["policy"]["thresholds"] == "not_calibrated"


def test_price_factor_identity_is_provenance_bound() -> None:
    first = evaluate(RecommendationPriceFactorExposureService(FakeRepository()), "provider-a")
    second = evaluate(RecommendationPriceFactorExposureService(FakeRepository()), "provider-b")
    assert first["factorExposureKey"] != second["factorExposureKey"]


def test_price_factors_fail_closed_on_late_knowledge() -> None:
    with pytest.raises((ValueError, RuntimeError), match="posterior|retrieved|PIT"):
        evaluate(RecommendationPriceFactorExposureService(FakeRepository(late=True)))


def test_price_factor_tampering_breaks_identity() -> None:
    service = RecommendationPriceFactorExposureService(FakeRepository())
    artifact = evaluate(service)
    artifact["factors"]["momentum"] = 99.0
    with pytest.raises(ValueError, match="factorExposureKey"):
        service.validate_artifact(artifact)


def test_price_factor_rejects_nonfinite_price() -> None:
    class BadRepository(FakeRepository):
        def list_for_instrument(self, instrument_id: int, **kwargs: object):
            rows = super().list_for_instrument(instrument_id, **kwargs)
            rows[5]["adjusted_close"] = float("nan")
            return rows

    with pytest.raises(ValueError, match="finito"):
        evaluate(RecommendationPriceFactorExposureService(BadRepository()))
