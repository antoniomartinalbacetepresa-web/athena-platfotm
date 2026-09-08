from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from app.services.recommendation_research_forecast_error_oos_service import (
    RecommendationResearchForecastErrorOosService,
)


AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
PERIOD_START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
HORIZON_30 = 30 * 86400
HORIZON_90 = 90 * 86400


def _row(
    *,
    seed: str,
    instrument_id: str,
    symbol: str,
    issuer_id: str | None,
    horizon_seconds: int,
    total_return: float,
) -> dict[str, object]:
    period_end = PERIOD_START + timedelta(seconds=horizon_seconds)
    return {
        "outcomeHash": (seed * 64)[:64],
        "cycleHash": ((seed + "c") * 64)[:64],
        "instrumentId": instrument_id,
        "symbol": symbol,
        "periodStart": PERIOD_START.isoformat(),
        "periodEnd": period_end.isoformat(),
        "horizonSeconds": horizon_seconds,
        "totalReturn": total_return,
        "issuerIdentity": {
            "status": "resolved" if issuer_id is not None else "unresolved",
            "issuerId": issuer_id,
            "availableAt": (AS_OF - timedelta(days=1)).isoformat(),
            "source": "athena-identity",
            "sourceRef": f"urn:issuer:{instrument_id}",
            "resolutionMethod": "canonical_security_master",
        },
    }


def _cohort(rows: list[dict[str, object]]) -> dict[str, object]:
    horizons: dict[str, dict[str, object]] = {}
    for row in rows:
        key = str(row["horizonSeconds"])
        horizon = horizons.setdefault(
            key,
            {
                "horizonSeconds": row["horizonSeconds"],
                "horizonDays": int(row["horizonSeconds"]) // 86400,
                "observationCount": 0,
            },
        )
        horizon["observationCount"] = int(horizon["observationCount"]) + 1
    return {
        "cohort_hash": "f" * 64,
        "artifact": {
            "module": "research_outcome_oos_cohort",
            "cohortId": "cohort-errors",
            "cohortHash": "f" * 64,
            "asOf": (AS_OF - timedelta(hours=1)).isoformat(),
            "observationCount": len(rows),
            "horizons": horizons,
            "rows": rows,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "productionLearningEligible": False,
        },
    }


def _error(
    row: dict[str, object],
    *,
    error_seed: str,
    expected: float,
    created_at: datetime | None = None,
) -> dict[str, object]:
    realized = float(row["totalReturn"])
    signed = realized - expected
    artifact = {
        "module": "research_forecast_error",
        "errorHash": (error_seed * 64)[:64],
        "specificationHash": ((error_seed + "s") * 64)[:64],
        "outcomeHash": row["outcomeHash"],
        "cycleHash": row["cycleHash"],
        "instrumentId": row["instrumentId"],
        "symbol": row["symbol"],
        "periodStart": row["periodStart"],
        "periodEnd": row["periodEnd"],
        "horizonSeconds": row["horizonSeconds"],
        "expectedValue": expected,
        "realizedValue": realized,
        "signedError": signed,
        "absoluteError": abs(signed),
        "squaredError": signed * signed,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "recommendationCandidateReady": False,
        "productionLearningEligible": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "skillClaim": "forbidden_single_observation_is_not_evidence_of_skill",
        },
    }
    return {
        "error_hash": artifact["errorHash"],
        "artifact": artifact,
        "created_at": (created_at or (AS_OF - timedelta(minutes=1))).isoformat(),
    }


def test_forecast_error_oos_computes_mae_mse_rmse_bias_and_issuer_diversity() -> None:
    first = _row(
        seed="a",
        instrument_id="instrument-a",
        symbol="AAA",
        issuer_id="issuer-shared",
        horizon_seconds=HORIZON_30,
        total_return=0.08,
    )
    second = _row(
        seed="b",
        instrument_id="instrument-b",
        symbol="AAB",
        issuer_id="issuer-shared",
        horizon_seconds=HORIZON_30,
        total_return=0.14,
    )
    service = RecommendationResearchForecastErrorOosService()
    result = service.evaluate(
        as_of=AS_OF,
        cohort_record=_cohort([first, second]),
        error_records=[
            _error(first, error_seed="1", expected=0.10),
            _error(second, error_seed="2", expected=0.10),
        ],
    )

    horizon = result["horizons"][str(HORIZON_30)]
    metrics = horizon["metrics"]
    assert result["forecastErrorCount"] == 2
    assert result["eligibleOutcomeCount"] == 2
    assert result["measurementCoverage"] == 1.0
    assert result["distinctResolvedIssuerCount"] == 1
    assert result["maximumErrorsPerResolvedIssuer"] == 2
    assert horizon["issuerErrorCounts"] == {"issuer-shared": 2}
    assert metrics["meanSignedError"] == pytest.approx(0.01)
    assert metrics["meanAbsoluteError"] == pytest.approx(0.03)
    assert metrics["meanSquaredError"] == pytest.approx(0.001)
    assert metrics["rootMeanSquaredError"] == pytest.approx(math.sqrt(0.001))
    assert metrics["meanExpectedValue"] == pytest.approx(0.10)
    assert metrics["meanRealizedValue"] == pytest.approx(0.11)
    assert result["policy"]["statisticalIndependence"] == "not_claimed"
    assert result["policy"]["skillClaim"] == "forbidden_descriptive_errors_are_not_proof_of_predictive_skill"
    assert result["productionLearningEligible"] is False
    assert result["isWeightingReady"] is False


def test_forecast_error_oos_reports_missing_coverage_and_keeps_horizons_separate() -> None:
    row_30 = _row(
        seed="c",
        instrument_id="instrument-c",
        symbol="CCC",
        issuer_id="issuer-c",
        horizon_seconds=HORIZON_30,
        total_return=0.04,
    )
    row_90 = _row(
        seed="d",
        instrument_id="instrument-d",
        symbol="DDD",
        issuer_id="issuer-d",
        horizon_seconds=HORIZON_90,
        total_return=0.12,
    )
    result = RecommendationResearchForecastErrorOosService().evaluate(
        as_of=AS_OF,
        cohort_record=_cohort([row_30, row_90]),
        error_records=[_error(row_30, error_seed="3", expected=0.05)],
    )

    assert result["forecastErrorCount"] == 1
    assert result["eligibleOutcomeCount"] == 2
    assert result["measurementCoverage"] == 0.5
    h30 = result["horizons"][str(HORIZON_30)]
    h90 = result["horizons"][str(HORIZON_90)]
    assert h30["forecastErrorCount"] == 1
    assert h30["measurementCoverage"] == 1.0
    assert h30["metrics"] is not None
    assert h90["forecastErrorCount"] == 0
    assert h90["missingForecastErrorCount"] == 1
    assert h90["measurementCoverage"] == 0.0
    assert h90["metrics"] is None
    assert result["policy"]["horizonPooling"] == "forbidden_exact_elapsed_horizons_only"


def test_forecast_error_oos_rejects_error_outside_cohort_future_or_realized_mismatch() -> None:
    row = _row(
        seed="e",
        instrument_id="instrument-e",
        symbol="EEE",
        issuer_id="issuer-e",
        horizon_seconds=HORIZON_30,
        total_return=0.07,
    )
    outside = _row(
        seed="9",
        instrument_id="instrument-x",
        symbol="XXX",
        issuer_id="issuer-x",
        horizon_seconds=HORIZON_30,
        total_return=0.03,
    )
    service = RecommendationResearchForecastErrorOosService()

    with pytest.raises(ValueError, match="fuera de la cohorte"):
        service.evaluate(
            as_of=AS_OF,
            cohort_record=_cohort([row]),
            error_records=[_error(outside, error_seed="4", expected=0.02)],
        )

    with pytest.raises(ValueError, match="después del as_of"):
        service.evaluate(
            as_of=AS_OF,
            cohort_record=_cohort([row]),
            error_records=[
                _error(
                    row,
                    error_seed="5",
                    expected=0.02,
                    created_at=AS_OF + timedelta(seconds=1),
                )
            ],
        )

    mismatch = _error(row, error_seed="6", expected=0.02)
    mismatch["artifact"]["realizedValue"] = 0.99
    with pytest.raises(ValueError, match="realizedValue"):
        service.evaluate(
            as_of=AS_OF,
            cohort_record=_cohort([row]),
            error_records=[mismatch],
        )


def test_forecast_error_oos_pending_without_cohort_is_safe() -> None:
    result = RecommendationResearchForecastErrorOosService().evaluate(
        as_of=AS_OF,
        cohort_record=None,
        error_records=[],
    )
    assert result["status"] == "forecast_error_oos_evidence_pending"
    assert result["forecastErrorCount"] == 0
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["productionLearningEligible"] is False
    assert result["policy"]["automaticModelMutation"] is False
    assert result["policy"]["thresholds"] == "none_selected_here"
