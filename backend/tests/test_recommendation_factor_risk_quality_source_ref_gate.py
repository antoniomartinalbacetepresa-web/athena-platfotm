from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
QUALITY_KEY = "7" * 64


class _Repository:
    def __init__(self, *, value: float = 0.4) -> None:
        self.value = value
        self.calls: list[str] = []

    def get(self, *, factor_exposure_key: str):
        self.calls.append(factor_exposure_key)
        if factor_exposure_key != QUALITY_KEY:
            return None
        return {
            "artifact": {
                "module": "pit_quality_factor_exposure",
                "factorExposureKey": QUALITY_KEY,
                "instrumentId": 11,
                "asOf": AS_OF.isoformat(),
                "availableAt": AVAILABLE_AT.isoformat(),
                "factors": {"quality": self.value},
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "isWeightingReady": False,
            }
        }


def _position(*, source_ref: str, quality: float = 0.4) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=11,
        symbol="AAA",
        weight=1.0,
        exposure_available_at=AVAILABLE_AT,
        source="sealed_market_beta+sealed_quality_factor+pit_factor_store",
        source_ref=source_ref,
        factors={"market": 1.0, "quality": quality},
    )


def test_quality_key_can_be_recovered_from_unique_sealed_source_ref() -> None:
    repository = _Repository()
    result = RecommendationFactorRiskService(quality_repository=repository).evaluate(
        as_of=AS_OF,
        positions=(
            _position(source_ref=f"market:{'a' * 64};caller:research;quality:{QUALITY_KEY}"),
        ),
    )

    payload = result.to_api_dict()
    assert payload["positions"][0]["factors"]["quality"] == pytest.approx(0.4)
    assert payload["factorCoverageWeights"]["quality"] == pytest.approx(1.0)
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert repository.calls == [QUALITY_KEY]


def test_quality_source_ref_gate_rejects_ambiguous_duplicate_keys() -> None:
    repository = _Repository()
    service = RecommendationFactorRiskService(quality_repository=repository)
    with pytest.raises(ValueError, match="sourceRef"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(source_ref=f"quality:{QUALITY_KEY};quality:{'8' * 64}"),
            ),
        )
    assert repository.calls == []


def test_quality_source_ref_gate_rejects_spoofed_value_even_with_real_key() -> None:
    repository = _Repository(value=0.4)
    service = RecommendationFactorRiskService(quality_repository=repository)
    with pytest.raises(ValueError, match="no reconcilia"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(source_ref=f"quality:{QUALITY_KEY}", quality=0.9),
            ),
        )
    assert repository.calls == [QUALITY_KEY]
