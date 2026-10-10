from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.services.recommendation_value_factor_exposure_service import (
    RecommendationValueFactorExposureService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 3, 1, 12, tzinfo=UTC)


class FakeInstrumentRepository:
    def __init__(self, instruments):
        self.instruments = list(instruments)

    def list_active(self):
        return list(self.instruments)


@dataclass(frozen=True)
class Resolution:
    issuer_id: int
    cik: str


class FakeCikResolver:
    def __init__(self, issuer_by_instrument=None, missing=None):
        self.issuer_by_instrument = issuer_by_instrument or {}
        self.missing = set(missing or [])

    def resolve(self, *, instrument_id):
        if instrument_id in self.missing:
            raise ValueError("sin identidad")
        issuer_id = self.issuer_by_instrument.get(instrument_id, instrument_id)
        return Resolution(issuer_id=issuer_id, cik=str(issuer_id).zfill(10))


class FakeBookToMarketService:
    def __init__(self, ratios=None, missing=None):
        self.ratios = ratios or {}
        self.missing = set(missing or [])

    def evaluate(self, *, instrument_id, as_of):
        assert as_of == AS_OF
        if instrument_id in self.missing:
            return {
                "module": "book_to_market_pit_evidence",
                "status": "missing",
                "evidenceKey": None,
                "bookToMarket": None,
            }
        ratio = self.ratios.get(instrument_id, float(instrument_id)) / 100.0
        return {
            "module": "book_to_market_pit_evidence",
            "status": "resolved",
            "evidenceKey": format(instrument_id, "064x"),
            "bookToMarket": ratio,
        }


def instruments(count=20):
    return [
        {
            "id": index,
            "symbol": f"S{index}",
            "instrument_type": "common_stock",
            "is_primary_listing": 1,
            "is_active": 1,
        }
        for index in range(1, count + 1)
    ]


def service(*, count=20, issuer_by_instrument=None, missing_identity=None, missing_book=None, ratios=None):
    return RecommendationValueFactorExposureService(
        instrument_repository=FakeInstrumentRepository(instruments(count)),
        cik_resolver=FakeCikResolver(issuer_by_instrument, missing_identity),
        book_to_market_service=FakeBookToMarketService(ratios=ratios, missing=missing_book),
    )


def test_value_factor_ranks_high_book_to_market_positive_and_is_bounded() -> None:
    result = service().evaluate(instrument_id=20, as_of=AS_OF)

    assert result["factors"] == {"value": 1.0}
    assert result["universeCount"] == 20
    assert result["bookToMarket"] == 0.20
    assert len(result["factorExposureKey"]) == 64
    assert len(result["universeFingerprint"]) == 64
    assert result["policy"]["thresholds"] == "not_calibrated"
    assert result["policy"]["statisticalIndependence"] == "not_claimed"
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False


def test_value_factor_ranks_low_book_to_market_negative_and_ties_at_average_rank() -> None:
    low = service().evaluate(instrument_id=1, as_of=AS_OF)
    assert low["factors"]["value"] == -1.0

    ratios = {index: float(index) for index in range(1, 21)}
    ratios[10] = 10.0
    ratios[11] = 10.0
    tied = service(ratios=ratios).evaluate(instrument_id=10, as_of=AS_OF)
    expected = 2.0 * ((9 + 0.5) / 19.0) - 1.0
    assert tied["factors"]["value"] == pytest.approx(expected)


def test_value_factor_excludes_non_primary_non_common_and_missing_evidence() -> None:
    rows = instruments(20)
    rows.extend(
        [
            {"id": 100, "instrument_type": "etf", "is_primary_listing": 1},
            {"id": 101, "instrument_type": "common_stock", "is_primary_listing": 0},
        ]
    )
    svc = RecommendationValueFactorExposureService(
        instrument_repository=FakeInstrumentRepository(rows),
        cik_resolver=FakeCikResolver(),
        book_to_market_service=FakeBookToMarketService(),
    )
    result = svc.evaluate(instrument_id=20, as_of=AS_OF)
    assert result["universeCount"] == 20

    with pytest.raises(ValueError, match="al menos 20"):
        service(missing_book={1}).evaluate(instrument_id=20, as_of=AS_OF)


def test_value_factor_excludes_duplicate_issuer_instead_of_double_counting() -> None:
    issuer_map = {19: 19, 20: 19}
    with pytest.raises(ValueError, match="múltiples listings primarios"):
        service(issuer_by_instrument=issuer_map).evaluate(instrument_id=20, as_of=AS_OF)

    with pytest.raises(ValueError, match="al menos 20"):
        service(issuer_by_instrument=issuer_map).evaluate(instrument_id=18, as_of=AS_OF)


def test_value_factor_requires_target_sec_identity_and_sufficient_universe() -> None:
    with pytest.raises(ValueError, match="identidad SEC"):
        service(missing_identity={20}).evaluate(instrument_id=20, as_of=AS_OF)
    with pytest.raises(ValueError, match="al menos 20"):
        service(count=19).evaluate(instrument_id=19, as_of=AS_OF)


def test_value_factor_rejects_naive_as_of_nonfinite_ratio_and_tampering() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        service().evaluate(instrument_id=20, as_of=datetime(2026, 3, 1, 12))

    with pytest.raises(ValueError, match="finito"):
        service(ratios={20: float("nan")}).evaluate(instrument_id=20, as_of=AS_OF)

    svc = service()
    artifact = svc.evaluate(instrument_id=20, as_of=AS_OF)
    artifact["factors"]["value"] = 0.5
    with pytest.raises(ValueError, match="factorExposureKey"):
        svc.validate_artifact(artifact)
