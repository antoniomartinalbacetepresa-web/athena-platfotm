from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_expectations_gap_service import (
    RecommendationExpectationsGapService,
)
from app.services.recommendation_reverse_valuation_service import (
    RecommendationReverseValuationService,
)
from app.services.recommendation_scenario_asymmetry_service import (
    RecommendationScenarioAsymmetryService,
    RecommendationScenarioInput,
)
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

valuation_service = RecommendationValuationSignalService()
reverse_valuation_service = RecommendationReverseValuationService(
    valuation_service=valuation_service,
)
expectations_gap_service = RecommendationExpectationsGapService(
    reverse_valuation_service=reverse_valuation_service,
)
scenario_asymmetry_service = RecommendationScenarioAsymmetryService(
    reverse_valuation_service=reverse_valuation_service,
)


def _effective_as_of(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return result.astimezone(timezone.utc)


def _payload(result: object, *, label: str) -> dict[str, object]:
    to_api_dict = getattr(result, "to_api_dict", None)
    if not callable(to_api_dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió un contrato inválido.")
    payload = to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió un contrato inválido.")
    return dict(payload)


def _assert_research_contract(payload: dict[str, object], *, label: str) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail=f"{label} violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail=f"{label} intentó habilitar producción.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail=f"{label} devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail=f"{label} intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") not in (None, False):
        raise HTTPException(status_code=500, detail=f"{label} intentó promover producción automáticamente.")


def _assert_expectations_contract(payload: dict[str, object]) -> None:
    _assert_research_contract(payload, label="Expectations Gap")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="Expectations Gap intentó declararse listo para ponderación.",
        )
    reference = payload.get("referenceExpectation")
    if not isinstance(reference, dict):
        raise HTTPException(status_code=500, detail="Expectations Gap perdió la evidencia de referencia.")
    required = ("kind", "metric", "horizonYears", "availableAt", "source", "sourceRef")
    if any(reference.get(field) in (None, "") for field in required):
        raise HTTPException(
            status_code=500,
            detail="Expectations Gap devolvió evidencia PIT incompleta.",
        )


def _assert_scenario_contract(payload: dict[str, object]) -> None:
    _assert_research_contract(payload, label="Scenario Asymmetry")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="Scenario Asymmetry intentó declararse listo para ponderación.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("probabilities") != (
        "not_assigned_no_expected_value_without_calibrated_probabilities"
    ):
        raise HTTPException(
            status_code=500,
            detail="Scenario Asymmetry intentó usar probabilidades no calibradas.",
        )
    scenarios = payload.get("scenarios")
    if payload.get("status") == "diagnostic_ready":
        if not isinstance(scenarios, list) or len(scenarios) != 3:
            raise HTTPException(
                status_code=500,
                detail="Scenario Asymmetry devolvió un conjunto de escenarios inválido.",
            )
        expected_names = ("bear", "base", "bull")
        for expected_name, scenario in zip(expected_names, scenarios):
            if not isinstance(scenario, dict) or scenario.get("name") != expected_name:
                raise HTTPException(
                    status_code=500,
                    detail="Scenario Asymmetry perdió el orden bear/base/bull.",
                )
            required = ("epsCagr", "exitPe", "annualizedReturn", "availableAt", "source", "sourceRef")
            if any(scenario.get(field) in (None, "") for field in required):
                raise HTTPException(
                    status_code=500,
                    detail="Scenario Asymmetry devolvió evidencia PIT incompleta.",
                )


def _scenario_input(
    *,
    name: str,
    eps_cagr: float,
    exit_pe: float,
    available_at: datetime,
    source: str,
    source_ref: str,
) -> RecommendationScenarioInput:
    return RecommendationScenarioInput(
        name=name,
        eps_cagr=eps_cagr,
        exit_pe=exit_pe,
        available_at=available_at,
        source=source,
        source_ref=source_ref,
    )


@router.get("/reverse-valuation")
def get_reverse_valuation(
    symbol: str = Query(..., min_length=1),
    horizon_years: int = Query(..., ge=1, le=50, alias="horizonYears"),
    required_return: float = Query(..., gt=-1.0, le=2.0, alias="requiredReturn"),
    exit_pe: float = Query(..., gt=0.0, le=500.0, alias="exitPe"),
    as_of: datetime | None = Query(None, alias="asOf"),
) -> dict[str, object]:
    """Expose an explicit PIT reverse-valuation diagnostic without advice."""

    effective_as_of = _effective_as_of(as_of)
    try:
        result = reverse_valuation_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
            horizon_years=horizon_years,
            required_return=required_return,
            exit_pe=exit_pe,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir la valoración inversa PIT de ATHENA.",
        ) from exc

    payload = _payload(result, label="Reverse Valuation")
    _assert_research_contract(payload, label="Reverse Valuation")
    return {"data": payload}


@router.get("/expectations-gap")
def get_expectations_gap(
    symbol: str = Query(..., min_length=1),
    horizon_years: int = Query(..., ge=1, le=50, alias="horizonYears"),
    required_return: float = Query(..., gt=-1.0, le=2.0, alias="requiredReturn"),
    exit_pe: float = Query(..., gt=0.0, le=500.0, alias="exitPe"),
    reference_eps_cagr: float = Query(..., gt=-1.0, le=10.0, alias="referenceEpsCagr"),
    expectation_kind: str = Query(..., min_length=1, alias="expectationKind"),
    expectation_metric: str = Query(..., min_length=1, alias="expectationMetric"),
    expectation_horizon_years: int = Query(..., ge=1, le=50, alias="expectationHorizonYears"),
    expectation_available_at: datetime = Query(..., alias="expectationAvailableAt"),
    expectation_source: str = Query(..., min_length=1, alias="expectationSource"),
    expectation_source_ref: str = Query(..., min_length=1, alias="expectationSourceRef"),
    as_of: datetime | None = Query(None, alias="asOf"),
) -> dict[str, object]:
    """Compare one typed PIT expectation with price-implied growth, research-only."""

    effective_as_of = _effective_as_of(as_of)
    try:
        result = expectations_gap_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
            horizon_years=horizon_years,
            required_return=required_return,
            exit_pe=exit_pe,
            reference_eps_cagr=reference_eps_cagr,
            expectation_kind=expectation_kind,
            expectation_metric=expectation_metric,
            expectation_horizon_years=expectation_horizon_years,
            expectation_available_at=expectation_available_at,
            expectation_source=expectation_source,
            expectation_source_ref=expectation_source_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir Expectations Gap PIT de ATHENA.",
        ) from exc

    payload = _payload(result, label="Expectations Gap")
    _assert_expectations_contract(payload)
    return {"data": payload}


@router.get("/scenario-asymmetry")
def get_scenario_asymmetry(
    symbol: str = Query(..., min_length=1),
    horizon_years: int = Query(..., ge=1, le=50, alias="horizonYears"),
    required_return: float = Query(..., gt=-1.0, le=2.0, alias="requiredReturn"),
    bear_eps_cagr: float = Query(..., gt=-1.0, le=10.0, alias="bearEpsCagr"),
    bear_exit_pe: float = Query(..., gt=0.0, le=500.0, alias="bearExitPe"),
    bear_available_at: datetime = Query(..., alias="bearAvailableAt"),
    bear_source: str = Query(..., min_length=1, alias="bearSource"),
    bear_source_ref: str = Query(..., min_length=1, alias="bearSourceRef"),
    base_eps_cagr: float = Query(..., gt=-1.0, le=10.0, alias="baseEpsCagr"),
    base_exit_pe: float = Query(..., gt=0.0, le=500.0, alias="baseExitPe"),
    base_available_at: datetime = Query(..., alias="baseAvailableAt"),
    base_source: str = Query(..., min_length=1, alias="baseSource"),
    base_source_ref: str = Query(..., min_length=1, alias="baseSourceRef"),
    bull_eps_cagr: float = Query(..., gt=-1.0, le=10.0, alias="bullEpsCagr"),
    bull_exit_pe: float = Query(..., gt=0.0, le=500.0, alias="bullExitPe"),
    bull_available_at: datetime = Query(..., alias="bullAvailableAt"),
    bull_source: str = Query(..., min_length=1, alias="bullSource"),
    bull_source_ref: str = Query(..., min_length=1, alias="bullSourceRef"),
    as_of: datetime | None = Query(None, alias="asOf"),
) -> dict[str, object]:
    """Evaluate provenance-bound PIT bear/base/bull outcomes without probabilities or advice."""

    effective_as_of = _effective_as_of(as_of)
    try:
        result = scenario_asymmetry_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
            horizon_years=horizon_years,
            required_return=required_return,
            bear=_scenario_input(
                name="bear",
                eps_cagr=bear_eps_cagr,
                exit_pe=bear_exit_pe,
                available_at=bear_available_at,
                source=bear_source,
                source_ref=bear_source_ref,
            ),
            base=_scenario_input(
                name="base",
                eps_cagr=base_eps_cagr,
                exit_pe=base_exit_pe,
                available_at=base_available_at,
                source=base_source,
                source_ref=base_source_ref,
            ),
            bull=_scenario_input(
                name="bull",
                eps_cagr=bull_eps_cagr,
                exit_pe=bull_exit_pe,
                available_at=bull_available_at,
                source=bull_source,
                source_ref=bull_source_ref,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir Scenario Asymmetry PIT de ATHENA.",
        ) from exc

    payload = _payload(result, label="Scenario Asymmetry")
    _assert_scenario_contract(payload)
    return {"data": payload}
