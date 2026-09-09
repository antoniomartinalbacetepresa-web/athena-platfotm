from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_quality_factor_exposure_service import (
    RecommendationQualityFactorExposureService,
)
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolution


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeInstrumentRepository:
    def __init__(self, count: int = 20) -> None:
        self.count = count

    def list_active(self) -> list[dict[str, object]]:
        return [
            {
                "id": index,
                "instrument_type": "common_stock",
                "is_primary_listing": 1,
            }
            for index in range(1, self.count + 1)
        ]


class FakeCikResolver:
    def __init__(self, duplicate_issuer: bool = False) -> None:
        self.duplicate_issuer = duplicate_issuer

    def resolve(self, *, instrument_id: int) -> SecInstrumentCikResolution:
        issuer_id = 1 if self.duplicate_issuer and instrument_id in (1, 2) else 1000 + instrument_id
        return SecInstrumentCikResolution(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            cik=str(instrument_id).zfill(10),
            issuer_name=f"Issuer {instrument_id}",
            link_confidence=1.0,
            external_id_confidence=1.0,
            evidence_source="test_identity",
            resolution_method="explicit_test",
            identity_key="a" * 64,
        )


class FakeMarginService:
    def __init__(self, *, equal: bool = False, missing_id: int | None = None) -> None:
        self.equal = equal
        self.missing_id = missing_id

    def evaluate(self, *, instrument_id: int, as_of: datetime) -> dict[str, object]:
        if instrument_id == self.missing_id:
            return {"status": "missing", "evidenceKey": None, "operatingMargin": None}
        margin = 0.1 if self.equal else instrument_id / 100.0
        return {
            "status": "resolved",
            "evidenceKey": f"{instrument_id % 16:x}" * 64,
            "operatingMargin": margin,
        }


def build_service(
    *,
    count: int = 20,
    duplicate_issuer: bool = False,
    equal: bool = False,
    missing_id: int | None = None,
) -> RecommendationQualityFactorExposureService:
    return RecommendationQualityFactorExposureService(
        instrument_repository=FakeInstrumentRepository(count=count),
        cik_resolver=FakeCikResolver(duplicate_issuer=duplicate_issuer),
        operating_margin_service=FakeMarginService(equal=equal, missing_id=missing_id),
    )


def test_quality_rank_is_bounded_deterministic_and_research_only() -> None:
    service = build_service()
    low = service.evaluate(instrument_id=1, as_of=AS_OF)
    high = service.evaluate(instrument_id=20, as_of=AS_OF)
    assert low["factors"]["quality"] == pytest.approx(-1.0)
    assert high["factors"]["quality"] == pytest.approx(1.0)
    assert low["universeCount"] == 20
    assert low["advisoryStatus"] == "no_advice"
    assert low["productionEligible"] is False
    assert low["isWeightingReady"] is False
    assert low["policy"]["thresholds"] == "not_calibrated"
    assert low["policy"]["sectorNeutralization"] == "not_performed_or_claimed"
    again = service.evaluate(instrument_id=1, as_of=AS_OF)
    assert again["universeFingerprint"] == low["universeFingerprint"]
    assert again["factorExposureKey"] == low["factorExposureKey"]


def test_quality_ties_use_average_rank_without_arbitrary_tiebreak() -> None:
    artifact = build_service(equal=True).evaluate(instrument_id=10, as_of=AS_OF)
    assert artifact["factors"]["quality"] == pytest.approx(0.0)


def test_quality_requires_minimum_unique_resolved_issuers() -> None:
    with pytest.raises(ValueError, match="al menos 20"):
        build_service(count=19).evaluate(instrument_id=1, as_of=AS_OF)
    with pytest.raises(ValueError, match="al menos 20"):
        build_service(missing_id=20).evaluate(instrument_id=1, as_of=AS_OF)


def test_quality_excludes_duplicate_primary_listings_by_issuer() -> None:
    with pytest.raises(ValueError, match="múltiples listings primarios"):
        build_service(count=22, duplicate_issuer=True).evaluate(instrument_id=1, as_of=AS_OF)


def test_quality_rejects_naive_time_and_detects_hash_tampering() -> None:
    service = build_service()
    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(instrument_id=1, as_of=datetime(2026, 1, 1))
    artifact = service.evaluate(instrument_id=1, as_of=AS_OF)
    artifact["factors"]["quality"] = 0.5
    with pytest.raises(ValueError, match="factorExposureKey"):
        service.validate_artifact(artifact)
