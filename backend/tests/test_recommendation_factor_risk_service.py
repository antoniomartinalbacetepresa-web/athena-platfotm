from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)
QUALITY_KEY_1 = "1" * 64
QUALITY_KEY_2 = "2" * 64


class _QualityRepository:
    def __init__(self, artifacts: dict[str, dict[str, object]] | None = None) -> None:
        self.artifacts = artifacts or {}
        self.calls: list[str] = []

    def get(self, *, factor_exposure_key: str) -> dict[str, object] | None:
        self.calls.append(factor_exposure_key)
        artifact = self.artifacts.get(factor_exposure_key)
        return None if artifact is None else {"artifact": dict(artifact)}


def _quality_artifact(
    *,
    key: str,
    instrument_id: int,
    value: float,
    as_of: datetime = AS_OF,
    available_at: datetime = AVAILABLE_AT,
) -> dict[str, object]:
    return {
        "module": "pit_quality_factor_exposure",
        "factorExposureKey": key,
        "instrumentId": instrument_id,
        "issuerId": instrument_id + 100,
        "asOf": as_of.isoformat(),
        "availableAt": available_at.isoformat(),
        "operatingMargin": value,
        "operatingMarginEvidenceKey": "a" * 64,
        "universeCount": 20,
        "universeFingerprint": "b" * 64,
        "factors": {"quality": value},
        "provenance": {},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "policy": {"automaticTrading": False},
    }


def _position(
    *,
    instrument_id: int,
    symbol: str,
    weight: float,
    factors: dict[str, float],
    available_at: datetime = AVAILABLE_AT,
    source: str = "pit_factor_store",
    source_ref: str | None = None,
    quality_exposure_key: str | None = None,
) -> FactorRiskPositionInput:
    return FactorRiskPositionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        weight=weight,
        exposure_available_at=available_at,
        source=source,
        source_ref=source_ref or f"factor:{instrument_id}:2025-12-31",
        factors=factors,
        quality_exposure_key=quality_exposure_key,
    )


def test_factor_risk_preserves_pit_provenance_and_reports_coverage() -> None:
    quality_repository = _QualityRepository(
        {
            QUALITY_KEY_1: _quality_artifact(key=QUALITY_KEY_1, instrument_id=1, value=0.5),
            QUALITY_KEY_2: _quality_artifact(key=QUALITY_KEY_2, instrument_id=2, value=-0.2),
        }
    )
    result = RecommendationFactorRiskService(quality_repository=quality_repository).evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.60,
                factors={"market": 1.2, "quality": 0.5, "usd_fx": 0.1},
                source="pit_factor_store+sealed_quality_factor",
                source_ref=f"factor:1:2025-12-31;quality:{QUALITY_KEY_1}",
                quality_exposure_key=QUALITY_KEY_1,
            ),
            _position(
                instrument_id=2,
                symbol="BBB",
                weight=0.30,
                factors={"market": 0.8, "quality": -0.2},
                source="pit_factor_store+sealed_quality_factor",
                source_ref=f"factor:2:2025-12-31;quality:{QUALITY_KEY_2}",
                quality_exposure_key=QUALITY_KEY_2,
            ),
        ),
    )

    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["investedWeight"] == pytest.approx(0.9)
    assert payload["cashWeight"] == pytest.approx(0.1)
    assert payload["weightedExposures"]["market"] == pytest.approx(0.96)
    assert payload["weightedExposures"]["quality"] == pytest.approx(0.24)
    assert payload["factorCoverageWeights"]["market"] == pytest.approx(0.9)
    assert payload["factorCoverageWeights"]["quality"] == pytest.approx(0.9)
    assert payload["factorCoverageWeights"]["usd_fx"] == pytest.approx(0.6)
    assert "market" in payload["fullyCoveredFactors"]
    assert "quality" in payload["fullyCoveredFactors"]
    assert "usd_fx" not in payload["fullyCoveredFactors"]
    assert payload["dominantFactor"] == "market"
    assert payload["positions"][0]["sourceRef"] == f"factor:1:2025-12-31;quality:{QUALITY_KEY_1}"
    assert payload["positions"][0]["exposureAvailableAt"] == AVAILABLE_AT.isoformat()
    assert payload["policy"]["missingFactorCoverage"] == "reported_explicitly_never_imputed_as_zero"
    assert payload["policy"]["quality"] == "quality_requires_persisted_tamper_verified_pit_factor_exposure_key"
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert quality_repository.calls == [QUALITY_KEY_1, QUALITY_KEY_2]


def test_factor_risk_rejects_unsealed_or_orphan_quality() -> None:
    service = RecommendationFactorRiskService(quality_repository=_QualityRepository())

    with pytest.raises(ValueError, match="quality_exposure_key"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0, "quality": 0.5},
                ),
            ),
        )

    with pytest.raises(ValueError, match="no puede existir sin factor quality"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                    quality_exposure_key=QUALITY_KEY_1,
                ),
            ),
        )


def test_factor_risk_quality_gate_rejects_missing_tampered_identity_time_and_provenance() -> None:
    base = _quality_artifact(key=QUALITY_KEY_1, instrument_id=1, value=0.5)

    cases: tuple[tuple[dict[str, object] | None, float, str, str, datetime, str], ...] = (
        (None, 0.5, "pit_factor_store+sealed_quality_factor", f"quality:{QUALITY_KEY_1}", AS_OF, "No existe quality"),
        (base, 0.4, "pit_factor_store+sealed_quality_factor", f"quality:{QUALITY_KEY_1}", AS_OF, "no reconcilia"),
        ({**base, "instrumentId": 2}, 0.5, "pit_factor_store+sealed_quality_factor", f"quality:{QUALITY_KEY_1}", AS_OF, "otro instrumento"),
        ({**base, "asOf": (AS_OF - timedelta(days=1)).isoformat()}, 0.5, "pit_factor_store+sealed_quality_factor", f"quality:{QUALITY_KEY_1}", AS_OF, "otro as_of"),
        (base, 0.5, "pit_factor_store", f"quality:{QUALITY_KEY_1}", AS_OF, "provenance"),
        (base, 0.5, "pit_factor_store+sealed_quality_factor", "quality:wrong", AS_OF, "sourceRef"),
        ({**base, "productionEligible": True}, 0.5, "pit_factor_store+sealed_quality_factor", f"quality:{QUALITY_KEY_1}", AS_OF, "producción/weighting"),
    )
    for artifact, value, source, source_ref, cutoff, match in cases:
        repository = _QualityRepository({QUALITY_KEY_1: artifact} if artifact is not None else {})
        service = RecommendationFactorRiskService(quality_repository=repository)
        with pytest.raises(ValueError, match=match):
            service.evaluate(
                as_of=cutoff,
                positions=(
                    _position(
                        instrument_id=1,
                        symbol="AAA",
                        weight=1.0,
                        factors={"market": 1.0, "quality": value},
                        source=source,
                        source_ref=source_ref,
                        quality_exposure_key=QUALITY_KEY_1,
                    ),
                ),
            )


def test_factor_risk_quality_gate_rejects_future_availability_and_out_of_range_value() -> None:
    future = _quality_artifact(
        key=QUALITY_KEY_1,
        instrument_id=1,
        value=0.5,
        available_at=AS_OF + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="PIT"):
        RecommendationFactorRiskService(
            quality_repository=_QualityRepository({QUALITY_KEY_1: future})
        ).evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0, "quality": 0.5},
                    source="pit_factor_store+sealed_quality_factor",
                    source_ref=f"quality:{QUALITY_KEY_1}",
                    quality_exposure_key=QUALITY_KEY_1,
                ),
            ),
        )

    out_of_range = _quality_artifact(key=QUALITY_KEY_1, instrument_id=1, value=1.5)
    with pytest.raises(ValueError, match=r"\[-1,1\]"):
        RecommendationFactorRiskService(
            quality_repository=_QualityRepository({QUALITY_KEY_1: out_of_range})
        ).evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0, "quality": 1.5},
                    source="pit_factor_store+sealed_quality_factor",
                    source_ref=f"quality:{QUALITY_KEY_1}",
                    quality_exposure_key=QUALITY_KEY_1,
                ),
            ),
        )


def test_factor_risk_does_not_select_dominant_factor_from_partial_coverage() -> None:
    result = RecommendationFactorRiskService().evaluate(
        as_of=AS_OF,
        positions=(
            _position(
                instrument_id=1,
                symbol="AAA",
                weight=0.50,
                factors={"market": 0.2, "usd_fx": 5.0},
            ),
            _position(
                instrument_id=2,
                symbol="BBB",
                weight=0.50,
                factors={"market": 0.3},
            ),
        ),
    )

    payload = result.to_api_dict()
    assert payload["weightedExposures"]["usd_fx"] == pytest.approx(2.5)
    assert payload["factorCoverageWeights"]["usd_fx"] == pytest.approx(0.5)
    assert "usd_fx" not in payload["fullyCoveredFactors"]
    assert payload["dominantFactor"] == "market"
    assert payload["grossFactorExposure"] == pytest.approx(0.25)


def test_factor_risk_rejects_lookahead_and_naive_timestamps() -> None:
    service = RecommendationFactorRiskService()

    with pytest.raises(ValueError, match="look-ahead"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                    available_at=AS_OF + timedelta(microseconds=1),
                ),
            ),
        )

    with pytest.raises(ValueError, match="zona horaria"):
        service.evaluate(
            as_of=datetime(2026, 1, 1),
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                ),
            ),
        )


def test_factor_risk_rejects_duplicate_identity_and_invalid_portfolio_weight() -> None:
    service = RecommendationFactorRiskService()

    with pytest.raises(ValueError, match="duplicados"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(instrument_id=1, symbol="AAA", weight=0.5, factors={"market": 1.0}),
                _position(instrument_id=1, symbol="BBB", weight=0.5, factors={"market": 1.0}),
            ),
        )

    with pytest.raises(ValueError, match="suma de weights"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(instrument_id=1, symbol="AAA", weight=0.7, factors={"market": 1.0}),
                _position(instrument_id=2, symbol="BBB", weight=0.4, factors={"market": 1.0}),
            ),
        )


def test_factor_risk_rejects_non_finite_unknown_and_missing_provenance() -> None:
    service = RecommendationFactorRiskService()

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finito"):
            service.evaluate(
                as_of=AS_OF,
                positions=(
                    _position(
                        instrument_id=1,
                        symbol="AAA",
                        weight=1.0,
                        factors={"market": value},
                    ),
                ),
            )

    with pytest.raises(ValueError, match="Factor no soportado"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"magic_alpha": 1.0},
                ),
            ),
        )

    with pytest.raises(ValueError, match="source_ref"):
        service.evaluate(
            as_of=AS_OF,
            positions=(
                _position(
                    instrument_id=1,
                    symbol="AAA",
                    weight=1.0,
                    factors={"market": 1.0},
                    source_ref=" ",
                ),
            ),
        )
