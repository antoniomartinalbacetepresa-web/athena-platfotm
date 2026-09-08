from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.services.recommendation_research_forecast_error_oos_summary_service import (
    RecommendationResearchForecastErrorOosSummaryService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 9, 1, tzinfo=UTC)
HORIZON = 30 * 86400


def canonical_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def specification(index: int, *, method: str = "athena-v1", start_day: int = 1) -> dict[str, object]:
    start = datetime(2026, 6, start_day, tzinfo=UTC)
    end = start + timedelta(seconds=HORIZON)
    cycle_hash = sha(f"cycle-{index}")
    evidence = {
        "availableAt": start.isoformat(),
        "source": "athena_research",
        "sourceRef": f"forecast-{index}",
        "method": method,
    }
    core = {
        "artifactVersion": "research-evaluation-specification-v1",
        "specificationId": f"spec-{index}",
        "cycleHash": cycle_hash,
        "instrumentId": f"instrument-{index}",
        "symbol": f"SYM{index}",
        "cycleAsOf": start.isoformat(),
        "metric": "total_return",
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "horizonSeconds": HORIZON,
        "expectedValue": 0.10 + index * 0.01,
        "forecastEvidence": evidence,
    }
    artifact = {
        "module": "research_evaluation_specification",
        **core,
        "specificationHash": canonical_hash(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "recommendationCandidateReady": False,
        "productionLearningEligible": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "targetDefinition": "precommitted_before_or_at_frozen_cycle_as_of",
            "metricScope": "total_return_only_v1",
            "period": "starts_exactly_at_cycle_as_of_with_exact_elapsed_horizon",
            "postOutcomeEditing": "forbidden_append_only_persistence_required",
            "evaluation": "signed_and_absolute_error_only_no_hit_rate_or_skill_claim",
            "thresholds": "none_selected_here",
            "causalClaim": "forbidden",
        },
    }
    return {
        "specification_hash": artifact["specificationHash"],
        "artifact": artifact,
        "created_at": start.isoformat(),
    }


def error(spec_record: dict[str, object], index: int, *, realized_delta: float) -> dict[str, object]:
    spec = spec_record["artifact"]
    assert isinstance(spec, dict)
    expected = float(spec["expectedValue"])
    realized = expected + realized_delta
    core = {
        "artifactVersion": "research-forecast-error-v1",
        "specificationHash": spec["specificationHash"],
        "outcomeHash": sha(f"outcome-{index}"),
        "cycleHash": spec["cycleHash"],
        "instrumentId": spec["instrumentId"],
        "symbol": spec["symbol"],
        "metric": "total_return",
        "periodStart": spec["periodStart"],
        "periodEnd": spec["periodEnd"],
        "horizonSeconds": HORIZON,
        "expectedValue": expected,
        "realizedValue": realized,
        "signedError": realized_delta,
        "absoluteError": abs(realized_delta),
        "squaredError": realized_delta * realized_delta,
    }
    artifact = {
        "module": "research_forecast_error",
        **core,
        "errorHash": canonical_hash(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "recommendationCandidateReady": False,
        "productionLearningEligible": False,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "comparison": "exact_precommitted_specification_vs_exact_persisted_outcome",
            "metric": "signed_absolute_and_squared_error_only",
            "skillClaim": "forbidden_single_observation_is_not_evidence_of_skill",
            "thresholds": "none_selected_here",
            "hindsight": "forbidden_specification_must_predate_outcome_and_match_exact_period",
            "causalClaim": "forbidden",
        },
    }
    return {
        "error_hash": artifact["errorHash"],
        "artifact": artifact,
        "created_at": spec["periodEnd"],
    }


def dataset(*, second_method: str = "athena-v1", second_start_day: int = 15):
    first_spec = specification(1, start_day=1)
    second_spec = specification(2, method=second_method, start_day=second_start_day)
    return (
        [error(first_spec, 1, realized_delta=0.02), error(second_spec, 2, realized_delta=-0.04)],
        [first_spec, second_spec],
    )


def test_oos_summary_is_descriptive_pit_and_reports_overlap_without_claiming_skill() -> None:
    errors, specs = dataset()
    result = RecommendationResearchForecastErrorOosSummaryService().build(
        summary_id="athena-v1-30d",
        as_of=AS_OF,
        error_records=errors,
        specification_records=specs,
    )

    assert result["observationCount"] == 2
    assert result["distinctInstrumentCount"] == 2
    assert result["overlappingPeriodPairCount"] == 1
    assert abs(result["metrics"]["meanSignedError"] + 0.01) < 1e-12
    assert abs(result["metrics"]["meanAbsoluteError"] - 0.03) < 1e-12
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["productionLearningEligible"] is False
    assert result["policy"]["statisticalIndependence"] == "not_claimed"
    assert result["policy"]["thresholdCalibration"] == "not_calibrated"
    assert result["policy"]["recommendationReadiness"] == "not_established"
    assert result["policy"]["automaticTrading"] is False
    assert len(result["summaryHash"]) == 64
    RecommendationResearchForecastErrorOosSummaryService().validate_artifact(result)


def test_oos_summary_identity_is_order_independent() -> None:
    errors, specs = dataset(second_start_day=31)
    service = RecommendationResearchForecastErrorOosSummaryService()
    first = service.build(summary_id="stable", as_of=AS_OF, error_records=errors, specification_records=specs)
    second = service.build(
        summary_id="stable",
        as_of=AS_OF,
        error_records=list(reversed(errors)),
        specification_records=list(reversed(specs)),
    )
    assert first["summaryHash"] == second["summaryHash"]


def test_oos_summary_rejects_mixed_forecast_methods() -> None:
    errors, specs = dataset(second_method="different-model")
    with pytest.raises(ValueError, match="métodos"):
        RecommendationResearchForecastErrorOosSummaryService().build(
            summary_id="mixed",
            as_of=AS_OF,
            error_records=errors,
            specification_records=specs,
        )


def test_oos_summary_rejects_duplicate_error_identity() -> None:
    errors, specs = dataset()
    with pytest.raises(ValueError, match="errorHash duplicado"):
        RecommendationResearchForecastErrorOosSummaryService().build(
            summary_id="duplicate",
            as_of=AS_OF,
            error_records=[errors[0], errors[0]],
            specification_records=[specs[0], specs[0]],
        )


def test_oos_summary_rejects_late_persisted_evidence() -> None:
    errors, specs = dataset()
    errors[0]["created_at"] = "2026-09-02T00:00:00+00:00"
    with pytest.raises(ValueError, match="look-ahead"):
        RecommendationResearchForecastErrorOosSummaryService().build(
            summary_id="late",
            as_of=AS_OF,
            error_records=errors,
            specification_records=specs,
        )


def test_oos_summary_detects_tampering() -> None:
    errors, specs = dataset()
    service = RecommendationResearchForecastErrorOosSummaryService()
    artifact = service.build(summary_id="tamper", as_of=AS_OF, error_records=errors, specification_records=specs)
    artifact["metrics"]["meanAbsoluteError"] = 0.0
    with pytest.raises(ValueError, match="modificado"):
        service.validate_artifact(artifact)
