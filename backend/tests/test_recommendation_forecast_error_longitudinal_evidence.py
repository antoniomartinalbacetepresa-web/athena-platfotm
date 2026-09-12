from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.recommendation_research_forecast_error_oos_service import (
    RecommendationResearchForecastErrorOosService,
)


AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
HORIZON = 30 * 86400


def _row(*, seed: str, period_start: datetime) -> dict[str, object]:
    period_end = period_start + timedelta(seconds=HORIZON)
    return {
        "outcomeHash": (seed * 64)[:64],
        "cycleHash": ((seed + "c") * 64)[:64],
        "instrumentId": f"instrument-{seed}",
        "symbol": seed.upper() * 3,
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "horizonSeconds": HORIZON,
        "totalReturn": 0.05,
        "issuerIdentity": {
            "status": "resolved",
            "issuerId": f"issuer-{seed}",
            "availableAt": (AS_OF - timedelta(days=1)).isoformat(),
            "source": "athena-identity",
            "sourceRef": f"urn:issuer:{seed}",
            "resolutionMethod": "canonical_security_master",
        },
    }


def _cohort(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "cohort_hash": "f" * 64,
        "artifact": {
            "module": "research_outcome_oos_cohort",
            "cohortId": "longitudinal-regression",
            "cohortHash": "f" * 64,
            "asOf": (AS_OF - timedelta(hours=1)).isoformat(),
            "observationCount": len(rows),
            "horizons": {
                str(HORIZON): {
                    "horizonSeconds": HORIZON,
                    "horizonDays": 30,
                    "observationCount": len(rows),
                }
            },
            "rows": rows,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "productionLearningEligible": False,
        },
    }


def _error(row: dict[str, object], *, seed: str) -> dict[str, object]:
    expected = 0.04
    realized = float(row["totalReturn"])
    signed = realized - expected
    artifact = {
        "module": "research_forecast_error",
        "errorHash": (seed * 64)[:64],
        "specificationHash": ((seed + "a") * 64)[:64],
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
        "created_at": (AS_OF - timedelta(minutes=1)).isoformat(),
    }


def test_forecast_error_oos_distinguishes_snapshot_from_longitudinal_observations() -> None:
    first = _row(seed="a", period_start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    second = _row(seed="b", period_start=datetime(2026, 3, 1, tzinfo=timezone.utc))

    service = RecommendationResearchForecastErrorOosService()
    longitudinal = service.evaluate(
        as_of=AS_OF,
        cohort_record=_cohort([first, second]),
        error_records=[_error(first, seed="1"), _error(second, seed="2")],
    )

    assert longitudinal["distinctEvaluationPeriodCount"] == 2
    assert longitudinal["evaluationSpanDays"] == 59.0
    assert longitudinal["longitudinalEvidenceStatus"] == "multiple_evaluation_periods_observed"
    assert longitudinal["firstEvaluationPeriodEnd"] < longitudinal["lastEvaluationPeriodEnd"]
    assert longitudinal["longitudinalSufficiency"]["status"] == "policy_not_precommitted"
    assert longitudinal["longitudinalSufficiency"]["policyApproved"] is False
    assert longitudinal["longitudinalSufficiency"]["productionSufficiencyClaimed"] is False

    horizon = longitudinal["horizons"][str(HORIZON)]
    assert horizon["distinctEvaluationPeriodCount"] == 2
    assert horizon["evaluationSpanDays"] == 59.0
    assert horizon["longitudinalEvidenceStatus"] == "multiple_evaluation_periods_observed"

    snapshot = service.evaluate(
        as_of=AS_OF,
        cohort_record=_cohort([first]),
        error_records=[_error(first, seed="3")],
    )
    assert snapshot["distinctEvaluationPeriodCount"] == 1
    assert snapshot["evaluationSpanDays"] == 0.0
    assert snapshot["longitudinalEvidenceStatus"] == "single_period_snapshot"


def test_forecast_error_oos_pending_never_claims_longitudinal_sufficiency() -> None:
    result = RecommendationResearchForecastErrorOosService().evaluate(
        as_of=AS_OF,
        cohort_record=None,
        error_records=[],
    )

    assert result["distinctEvaluationPeriodCount"] == 0
    assert result["evaluationSpanDays"] == 0.0
    assert result["longitudinalEvidenceStatus"] == "no_evaluated_periods"
    assert result["longitudinalSufficiency"] == {
        "status": "policy_not_precommitted",
        "policyId": None,
        "policyApproved": False,
        "productionSufficiencyClaimed": False,
    }
