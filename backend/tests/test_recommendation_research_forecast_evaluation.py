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
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)
from app.services.recommendation_research_outcome_attribution_service import (
    RecommendationResearchOutcomeAttributionService,
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
        now_provider=lambda: CYCLE_AS_OF,
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


@pytest.mark.parametrize("delay", [timedelta(microseconds=1), timedelta(days=1)])
def test_repository_rejects_sealing_after_period_start_before_maturity(tmp_path: Path, delay: timedelta) -> None:
    repository = RecommendationResearchEvaluationSpecificationRepository(
        AthenaDatabase(tmp_path / "late-start.db"),
        now_provider=lambda: CYCLE_AS_OF + delay,
    )
    with pytest.raises(ValueError, match="periodo ya comenzó"):
        repository.append(artifact=_specification())


def test_existing_precommitted_specification_can_be_retried_after_maturity(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "retry.db")
    artifact = _specification()
    first = _precommit_repository(database).append(artifact=artifact)
    later_repository = RecommendationResearchEvaluationSpecificationRepository(
        database, now_provider=lambda: CYCLE_AS_OF + timedelta(days=31),
    )
    assert later_repository.append(artifact=artifact) == first


def test_legacy_late_specification_fails_read_validation(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "legacy-late.db")
    repository = _precommit_repository(database)
    record = repository.append(artifact=_specification())
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_evaluation_specifications SET created_at = ? WHERE specification_hash = ?",
            ((CYCLE_AS_OF + timedelta(microseconds=1)).isoformat(), record["specification_hash"]),
        )
    with pytest.raises(ValueError, match="inicio de su periodo"):
        repository.get_by_hash(specification_hash=record["specification_hash"])


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


@pytest.mark.parametrize(
    ("created_at", "included"),
    [
        ("2026-06-01T14:00:00+02:00", True),
        ("2026-06-01T14:00:00.000001+02:00", False),
        ("2026-06-01T07:00:00-05:00", True),
        ("2026-06-01T07:00:01-05:00", False),
        ("2026-06-01T11:59:59.999999+00:00", True),
    ],
)
def test_forecast_error_pit_cutoff_compares_instants(
    tmp_path: Path, created_at: str, included: bool
) -> None:
    specification = _specification()
    outcome = _outcome_record()
    service = RecommendationResearchForecastErrorService()
    artifact = service.evaluate(
        specification_record={
            "specification_hash": specification["specificationHash"],
            "artifact": specification,
        },
        outcome_record=outcome,
    )
    database = AthenaDatabase(tmp_path / "offsets.db")
    repository = RecommendationResearchForecastErrorRepository(database, service)
    record = repository.append(artifact=artifact)
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_forecast_errors SET created_at = ? WHERE error_hash = ?",
            (created_at, record["error_hash"]),
        )
    result = repository.get_for_outcomes_at_or_before(
        outcome_hashes=[outcome["outcome_hash"]],
        as_of=datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
    )
    assert [row["error_hash"] for row in result] == (
        [record["error_hash"]] if included else []
    )


def test_forecast_error_reverifies_specification_hash_not_only_database_column() -> None:
    specification = _specification()
    specification["expectedValue"] = 0.99
    with pytest.raises(ValueError, match="specificationHash"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={"specification_hash": specification["specificationHash"], "artifact": specification},
            outcome_record=_outcome_record(),
        )


def test_forecast_error_reverifies_original_outcome_hash() -> None:
    specification = _specification()
    outcome = _outcome_record()
    outcome["payload"]["attribution"]["totalReturn"] = 0.99
    with pytest.raises(ValueError, match="outcomeHash"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={"specification_hash": specification["specificationHash"], "artifact": specification},
            outcome_record=outcome,
        )


def test_forecast_error_rejects_rehashed_attribution_with_different_period() -> None:
    specification = _specification()
    outcome = _outcome_record()
    payload = outcome["payload"]
    payload["attribution"]["periodEnd"] = (CYCLE_AS_OF + timedelta(days=31)).isoformat()
    payload["outcomeHash"] = _canonical_hash({
        "outcomeId": payload["outcomeId"], "cycleHash": payload["cycleHash"],
        "instrumentId": payload["instrumentId"], "symbol": payload["symbol"],
        "cycleAsOf": payload["cycleAsOf"], "attribution": payload["attribution"],
    })
    outcome["outcome_hash"] = payload["outcomeHash"]
    with pytest.raises(ValueError, match="outcome.periodEnd"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={"specification_hash": specification["specificationHash"], "artifact": specification},
            outcome_record=outcome,
        )


def test_forecast_error_rejects_late_physical_precommit_when_present() -> None:
    specification = _specification()
    with pytest.raises(ValueError, match="sellada ex-ante"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={
                "specification_hash": specification["specificationHash"],
                "artifact": specification,
                "created_at": (CYCLE_AS_OF + timedelta(microseconds=1)).isoformat(),
            },
            outcome_record=_outcome_record(),
        )


def test_forecast_error_rejects_outcome_persisted_before_observation_when_present() -> None:
    specification = _specification()
    outcome = _outcome_record()
    outcome["created_at"] = (CYCLE_AS_OF + timedelta(days=29)).isoformat()
    with pytest.raises(ValueError, match="antes de su observación"):
        RecommendationResearchForecastErrorService().evaluate(
            specification_record={"specification_hash": specification["specificationHash"], "artifact": specification},
            outcome_record=outcome,
        )


def _canonical_attribution(
    *,
    evidence_time: datetime | None = None,
    total_source: str = "observed-return",
    market_source: str = "market-index",
) -> dict:
    period_end = CYCLE_AS_OF + timedelta(days=30)
    available_at = evidence_time if evidence_time is not None else period_end

    def component(value: float, source: str) -> AttributionEvidence:
        return AttributionEvidence(
            value=value,
            available_at=available_at,
            source=source,
            source_ref=f"urn:research:attribution:{source}",
        )

    return RecommendationPerformanceAttributionService().evaluate(
        as_of=period_end,
        item=RecommendationPerformanceAttributionInput(
            instrument_id="instrument-aapl",
            symbol="AAPL",
            instrument_currency="USD",
            reporting_currency="USD",
            fx_pair="USD/USD",
            benchmark_id="SPY",
            period_start=CYCLE_AS_OF,
            period_end=period_end,
            total_return=component(0.08, total_source),
            market_contribution=component(0.03, market_source),
            fx_contribution=component(0.0, "fx-zero"),
            factor_contributions=(),
        ),
    ).to_api_dict()


def _canonical_outcome_record() -> dict:
    payload = RecommendationResearchOutcomeAttributionService().bind(
        outcome_id="outcome-aapl-canonical",
        cycle_record=_cycle_record(),
        attribution_payload=_canonical_attribution(),
    )
    return {
        "outcome_hash": payload["outcomeHash"],
        "cycle_hash": CYCLE_HASH,
        "payload": payload,
    }


def _recommit_canonical_outcome(outcome: dict, attribution: dict | None = None) -> None:
    payload = outcome["payload"]
    if attribution is not None:
        payload["attribution"] = attribution
        payload["attributionKey"] = attribution["attributionKey"]
    payload["outcomeHash"] = _canonical_hash({
        "outcomeId": payload["outcomeId"],
        "cycleHash": payload["cycleHash"],
        "instrumentId": payload["instrumentId"],
        "symbol": payload["symbol"],
        "cycleAsOf": payload["cycleAsOf"],
        "attribution": payload["attribution"],
    })
    outcome["outcome_hash"] = payload["outcomeHash"]


def _evaluate_canonical_outcome(outcome: dict) -> dict:
    specification = _specification()
    return RecommendationResearchForecastErrorService().evaluate(
        specification_record={
            "specification_hash": specification["specificationHash"],
            "artifact": specification,
        },
        outcome_record=outcome,
    )


def test_forecast_error_accepts_producer_bound_canonical_attribution() -> None:
    result = _evaluate_canonical_outcome(_canonical_outcome_record())
    assert result["realizedValue"] == pytest.approx(0.08)
    assert result["productionEligible"] is False
    assert result["productionLearningEligible"] is False


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("attributionKey", "f" * 64),
        ("benchmarkId", "OTHER-BENCHMARK"),
        ("currency", {"instrumentCurrency": "EUR", "reportingCurrency": "USD",
                      "fxPair": "EUR/USD", "conversionRequired": True}),
    ],
)
def test_forecast_error_rejects_canonical_outer_identity_forgery(field: str, forged: object) -> None:
    outcome = _canonical_outcome_record()
    outcome["payload"][field] = forged
    with pytest.raises(ValueError, match="canónic"):
        _evaluate_canonical_outcome(outcome)


def test_forecast_error_rejects_forged_nested_return_with_rehashed_outer_outcome() -> None:
    outcome = _canonical_outcome_record()
    attribution = outcome["payload"]["attribution"]
    attribution["totalReturn"] = 0.25
    attribution["residualReturn"] = 0.22
    _recommit_canonical_outcome(outcome)
    with pytest.raises(ValueError, match="Performance Attribution"):
        _evaluate_canonical_outcome(outcome)


def test_forecast_error_rejects_canonical_evidence_before_horizon_maturity() -> None:
    outcome = _canonical_outcome_record()
    premature = _canonical_attribution(
        evidence_time=CYCLE_AS_OF + timedelta(days=30, seconds=-1)
    )
    _recommit_canonical_outcome(outcome, premature)
    with pytest.raises(ValueError, match="antes de cerrar el periodo"):
        _evaluate_canonical_outcome(outcome)


def test_forecast_error_rejects_canonical_fmp_provenance_even_when_rehashed() -> None:
    outcome = _canonical_outcome_record()
    forbidden = _canonical_attribution(total_source="Financial Modeling Prep")
    _recommit_canonical_outcome(outcome, forbidden)
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        _evaluate_canonical_outcome(outcome)


def test_forecast_error_rejects_duplicate_canonical_component_provenance() -> None:
    outcome = _canonical_outcome_record()
    duplicated = _canonical_attribution(market_source="observed-return")
    _recommit_canonical_outcome(outcome, duplicated)
    with pytest.raises(ValueError, match="provenance duplicada"):
        _evaluate_canonical_outcome(outcome)
