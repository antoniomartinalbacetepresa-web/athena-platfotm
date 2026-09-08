from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_research_evaluation_specification_repository import (
    RecommendationResearchEvaluationSpecificationRepository,
)
from app.repositories.recommendation_research_forecast_error_repository import (
    RecommendationResearchForecastErrorRepository,
)
from app.services.recommendation_research_evaluation_specification_service import (
    RecommendationResearchEvaluationSpecificationService,
)
from app.services.recommendation_research_forecast_error_service import (
    RecommendationResearchForecastErrorService,
)


CYCLE_AS_OF = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
CYCLE_HASH = hashlib.sha256(b"cycle-forecast-test").hexdigest()


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _cycle_record() -> dict[str, object]:
    cycle = {
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": CYCLE_AS_OF.isoformat(),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "integrity": {"cycleHash": CYCLE_HASH},
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        },
    }
    return {
        "cycle_hash": CYCLE_HASH,
        "package": {"cycle": cycle},
    }


def _specification(*, expected: float = 0.12, horizon_seconds: int = 30 * 86400):
    return RecommendationResearchEvaluationSpecificationService().build(
        specification_id="spec-aapl-30d",
        cycle_record=_cycle_record(),
        horizon_seconds=horizon_seconds,
        expected_total_return=expected,
        available_at=CYCLE_AS_OF - timedelta(minutes=5),
        source="athena-internal-research",
        source_ref="urn:athena:forecast:aapl:30d",
        method="frozen_research_model_v1",
    )


def _outcome_record(*, total_return: float = 0.08, horizon_seconds: int = 30 * 86400):
    period_end = CYCLE_AS_OF + timedelta(seconds=horizon_seconds)
    attribution = {
        "module": "performance_attribution",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": period_end.isoformat(),
        "periodStart": CYCLE_AS_OF.isoformat(),
        "periodEnd": period_end.isoformat(),
        "totalReturn": total_return,
        "marketContribution": 0.03,
        "fxContribution": 0.0,
        "factorContributions": {},
        "explainedReturn": 0.03,
        "residualReturn": total_return - 0.03,
        "evidence": {},
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "causalClaim": "forbidden_arithmetic_attribution_only",
            "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
            "fx": "explicit_not_silently_neutralized",
        },
    }
    canonical = {
        "outcomeId": "outcome-aapl-30d",
        "cycleHash": CYCLE_HASH,
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "cycleAsOf": CYCLE_AS_OF.isoformat(),
        "attribution": attribution,
    }
    outcome_hash = _canonical_hash(canonical)
    payload = {
        "module": "research_outcome_attribution",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "outcomeId": "outcome-aapl-30d",
        "outcomeHash": outcome_hash,
        "cycleHash": CYCLE_HASH,
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "cycleAsOf": CYCLE_AS_OF.isoformat(),
        "asOf": period_end.isoformat(),
        "periodStart": CYCLE_AS_OF.isoformat(),
        "periodEnd": period_end.isoformat(),
        "attribution": attribution,
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "learning": "research_only_not_automatic_model_update",
            "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
            "fx": "explicit_not_silently_neutralized",
        },
    }
    return {
        "outcome_hash": outcome_hash,
        "cycle_hash": CYCLE_HASH,
        "payload": payload,
    }


def _precommit_repository(database: AthenaDatabase):
    return RecommendationResearchEvaluationSpecificationRepository(
        database,
        RecommendationResearchEvaluationSpecificationService(),
        now_provider=lambda: CYCLE_AS_OF + timedelta(minutes=1),
    )


def test_specification_is_frozen_before_outcome_and_research_only() -> None:
    artifact = _specification()
    assert artifact["metric"] == "total_return"
    assert artifact["periodStart"] == CYCLE_AS_OF.isoformat()
    assert artifact["periodEnd"] == (CYCLE_AS_OF + timedelta(days=30)).isoformat()
    assert artifact["expectedValue"] == 0.12
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["productionLearningEligible"] is False
    assert artifact["policy"]["automaticModelMutation"] is False
    assert artifact["policy"]["thresholds"] == "none_selected_here"


def test_specification_rejects_declared_hindsight_and_fmp() -> None:
    service = RecommendationResearchEvaluationSpecificationService()
    with pytest.raises(ValueError, match="a más tardar"):
        service.build(
            specification_id="spec-future",
            cycle_record=_cycle_record(),
            horizon_seconds=86400,
            expected_total_return=0.01,
            available_at=CYCLE_AS_OF + timedelta(seconds=1),
            source="athena",
            source_ref="urn:forecast:future",
            method="test",
        )
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        service.build(
            specification_id="spec-fmp",
            cycle_record=_cycle_record(),
            horizon_seconds=86400,
            expected_total_return=0.01,
            available_at=CYCLE_AS_OF,
            source="Financial Modeling Prep",
            source_ref="urn:forecast:fmp",
            method="test",
        )


def test_repository_rejects_physical_retroactive_sealing(tmp_path: Path) -> None:
    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "retroactive.db"),
        RecommendationResearchEvaluationSpecificationService(),
        now_provider=lambda: CYCLE_AS_OF + timedelta(days=30),
    )
    with pytest.raises(ValueError, match="no puede sellarse retrospectivamente"):
        repository.append(artifact=_specification())


def test_specification_repository_prevents_moving_goalposts(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "spec.db")
    service = RecommendationResearchEvaluationSpecificationService()
    repository = _precommit_repository(database)
    first = _specification(expected=0.12)
    same = repository.append(artifact=first)
    assert repository.append(artifact=first)["specification_hash"] == same["specification_hash"]
    assert datetime.fromisoformat(same["created_at"]) < datetime.fromisoformat(first["periodEnd"])

    changed = service.build(
        specification_id="spec-aapl-30d-changed",
        cycle_record=_cycle_record(),
        horizon_seconds=30 * 86400,
        expected_total_return=0.20,
        available_at=CYCLE_AS_OF - timedelta(minutes=5),
        source="athena-internal-research",
        source_ref="urn:athena:forecast:aapl:changed",
        method="frozen_research_model_v1",
    )
    with pytest.raises(ValueError, match="mover el objetivo"):
        repository.append(artifact=changed)


def test_forecast_error_uses_exact_precommitted_period_and_reconciles() -> None:
    specification = _specification(expected=0.12)
    outcome = _outcome_record(total_return=0.08)
    service = RecommendationResearchForecastErrorService()
    result = service.evaluate(
        specification_record={
            "specification_hash": specification["specificationHash"],
            "artifact": specification,
        },
        outcome_record=outcome,
    )
    assert result["expectedValue"] == 0.12
    assert result["realizedValue"] == 0.08
    assert result["signedError"] == pytest.approx(-0.04)
    assert result["absoluteError"] == pytest.approx(0.04)
    assert result["squaredError"] == pytest.approx(0.0016)
    assert result["policy"]["skillClaim"] == "forbidden_single_observation_is_not_evidence_of_skill"
    assert result["productionLearningEligible"] is False


def test_forecast_error_rejects_different_horizon() -> None:
    specification = _specification(horizon_seconds=30 * 86400)
    outcome = _outcome_record(horizon_seconds=90 * 86400)
    with pytest.raises(ValueError, match="no termina"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={
                "specification_hash": specification["specificationHash"],
                "artifact": specification,
            },
            outcome_record=outcome,
        )


def test_forecast_error_repository_is_idempotent_and_detects_tampering(tmp_path: Path) -> None:
    specification = _specification(expected=0.12)
    outcome = _outcome_record(total_return=0.08)
    service = RecommendationResearchForecastErrorService()
    artifact = service.evaluate(
        specification_record={
            "specification_hash": specification["specificationHash"],
            "artifact": specification,
        },
        outcome_record=outcome,
    )
    database = AthenaDatabase(tmp_path / "errors.db")
    repository = RecommendationResearchForecastErrorRepository(database, service)
    first = repository.append(artifact=artifact)
    assert repository.append(artifact=artifact)["error_hash"] == first["error_hash"]

    with database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_research_forecast_errors WHERE error_hash = ?",
            (first["error_hash"],),
        ).fetchone()
        mutated = json.loads(str(row["artifact_json"]))
        mutated["absoluteError"] = 999.0
        connection.execute(
            "UPDATE athena_research_forecast_errors SET artifact_json = ? WHERE error_hash = ?",
            (
                json.dumps(mutated, sort_keys=True, separators=(",", ":"), allow_nan=False),
                first["error_hash"],
            ),
        )
    with pytest.raises(ValueError):
        repository.get_by_hash(error_hash=first["error_hash"])


def test_forecast_evaluation_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/evaluation-specification" in paths
    assert "/api/v1/recommendations/professional-research/evaluation-specification/{specification_hash}" in paths
    assert "/api/v1/recommendations/professional-research/forecast-error" in paths
    assert "/api/v1/recommendations/professional-research/forecast-error/{error_hash}" in paths
