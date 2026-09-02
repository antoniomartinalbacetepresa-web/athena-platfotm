from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_shadow_holdout_seal_service import (
    RecommendationShadowHoldoutSealService,
)
from app.services.recommendation_shadow_live_decision_research_service import (
    RecommendationShadowLiveDecisionResearchService,
)
from app.services.recommendation_shadow_live_longitudinal_service import (
    RecommendationShadowLiveLongitudinalService,
)
from app.services.recommendation_shadow_research_pipeline_service import (
    RecommendationShadowResearchPipelineService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/learning",
    tags=["recommendations"],
)

research_pipeline_service = RecommendationShadowResearchPipelineService()
holdout_seal_service = RecommendationShadowHoldoutSealService()
live_longitudinal_service = RecommendationShadowLiveLongitudinalService()
live_decision_research_service = RecommendationShadowLiveDecisionResearchService()


def _effective_as_of(value: datetime | None) -> datetime:
    result = value if value is not None else datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise HTTPException(status_code=400, detail="as_of debe incluir zona horaria.")
    return result


def _parse_horizons(value: str) -> tuple[int, ...]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Se requiere al menos un horizonte.")
    try:
        horizons = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="horizons debe contener enteros positivos separados por comas.",
        ) from exc
    if any(horizon <= 0 for horizon in horizons):
        raise HTTPException(status_code=400, detail="Todos los horizontes deben ser positivos.")
    if len(set(horizons)) != len(horizons):
        raise HTTPException(status_code=400, detail="Los horizontes no pueden repetirse.")
    return horizons


def _assert_shadow_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow violó el contrato no-advice de ATHENA.",
        )
    if payload.get("productionEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow no puede habilitar producción.",
        )


def _assert_research_policy(payload: dict[str, object]) -> None:
    policy = payload.get("policy")
    if not isinstance(policy, dict) or policy.get("productionEligibility") is not False:
        raise HTTPException(
            status_code=500,
            detail="El pipeline shadow devolvió una política de producción inválida.",
        )


def _assert_holdout_policy(payload: dict[str, object]) -> None:
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(
            status_code=500,
            detail="El holdout shadow devolvió una política inválida.",
        )
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(
            status_code=500,
            detail="El holdout shadow no puede habilitar promoción automática.",
        )
    if policy.get("actions") != "not_assigned":
        raise HTTPException(
            status_code=500,
            detail="El holdout shadow no puede asignar acciones de inversión.",
        )

    multiplicity = payload.get("experimentMultiplicity")
    if isinstance(multiplicity, dict):
        experiment_count = multiplicity.get("distinctHoldoutExperimentCount")
        controlled = multiplicity.get("multiplicityControlled")
        correction = multiplicity.get("correctionMethod")
        try:
            parsed_count = int(experiment_count)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail="El holdout shadow devolvió multiplicidad inválida.",
            ) from exc
        if parsed_count < 0:
            raise HTTPException(
                status_code=500,
                detail="El holdout shadow devolvió multiplicidad inválida.",
            )
        if parsed_count > 1 and controlled is not False:
            raise HTTPException(
                status_code=500,
                detail="La API no puede declarar controlada una multiplicidad sin evidencia.",
            )
        if parsed_count > 1 and correction == "not_yet_implemented" and payload.get(
            "actionThresholdCalibrationResearchEligible"
        ) is not False:
            raise HTTPException(
                status_code=500,
                detail="La API no puede promover un holdout con multiplicidad no corregida.",
            )


def _assert_holdout_evidence_separation(payload: dict[str, object]) -> None:
    """Keep raw holdout evidence distinct from downstream promotion eligibility."""
    if "rawHoldoutGateEligible" not in payload:
        return
    raw_eligible = payload.get("rawHoldoutGateEligible")
    final_eligible = payload.get("actionThresholdCalibrationResearchEligible")
    if not isinstance(raw_eligible, bool) or not isinstance(final_eligible, bool):
        raise HTTPException(
            status_code=500,
            detail="El holdout shadow devolvió elegibilidad no booleana.",
        )

    multiplicity = payload.get("experimentMultiplicity")
    if not isinstance(multiplicity, dict):
        raise HTTPException(
            status_code=500,
            detail="Un holdout sellado debe exponer su multiplicidad experimental.",
        )
    controlled = multiplicity.get("multiplicityControlled")
    lineage_complete = multiplicity.get("firstExposureLineageComplete")
    if final_eligible and (
        not raw_eligible or controlled is not True or lineage_complete is not True
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "La elegibilidad final del holdout no está respaldada por evidencia "
                "y linaje válidos."
            ),
        )


def _assert_longitudinal_policy(payload: dict[str, object]) -> None:
    if payload.get("recommendationCandidateReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede habilitar recomendaciones.",
        )
    if payload.get("actionThresholdCalibrationResearchEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede promover calibración automáticamente.",
        )
    if payload.get("action") is not None:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede asignar acciones.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal devolvió una política inválida.",
        )
    if policy.get("modelVersionPooling") != (
        "forbidden_metrics_partitioned_by_frozen_model_fingerprint"
    ):
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede mezclar versiones de modelo.",
        )
    if policy.get("automaticModelMutation") is not False:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede mutar modelos automáticamente.",
        )
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede promover producción automáticamente.",
        )
    if policy.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="La medición longitudinal no puede habilitar trading automático.",
        )


def _assert_decision_research_policy(payload: dict[str, object]) -> None:
    if payload.get("recommendationCandidateReady") is not False:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede habilitar recomendaciones.",
        )
    if payload.get("actionThresholdCalibrationResearchEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede promover calibración automáticamente.",
        )
    if payload.get("action") is not None:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede asignar acciones.",
        )
    if payload.get("score") is not None or payload.get("conviction") is not None:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede publicar score o convicción sin calibrar.",
        )
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(
            status_code=500,
            detail="Decision research devolvió una política inválida.",
        )
    if policy.get("actionThresholds") != "not_fit":
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede utilizar umbrales de acción no validados.",
        )
    if policy.get("score") != "not_calibrated" or policy.get("conviction") != "not_calibrated":
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede declarar score o convicción calibrados.",
        )
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede promover producción automáticamente.",
        )
    if policy.get("automaticTrading") is not False:
        raise HTTPException(
            status_code=500,
            detail="Decision research no puede habilitar trading automático.",
        )


@router.get("/shadow-research-readiness")
def get_shadow_research_readiness(
    as_of: datetime | None = Query(None),
    horizons: str = Query("7,30,90,180,365"),
) -> dict[str, object]:
    """Run the PIT research pipeline without producing investment advice."""

    effective_as_of = _effective_as_of(as_of)
    effective_horizons = _parse_horizons(horizons)
    try:
        payload = research_pipeline_service.evaluate(
            as_of=effective_as_of,
            horizons=effective_horizons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar la preparación shadow de ATHENA.",
        ) from exc

    _assert_shadow_contract(payload)
    _assert_research_policy(payload)
    return {"data": payload}


@router.get("/shadow-holdout-readiness")
def get_shadow_holdout_readiness(
    as_of: datetime | None = Query(None),
    horizons: str = Query("7,30,90,180,365"),
) -> dict[str, object]:
    """Evaluate and immutably seal the first sufficiently mature holdout result."""

    effective_as_of = _effective_as_of(as_of)
    effective_horizons = _parse_horizons(horizons)
    try:
        payload = holdout_seal_service.evaluate_and_seal(
            as_of=effective_as_of,
            horizons=effective_horizons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar el holdout shadow de ATHENA.",
        ) from exc

    _assert_shadow_contract(payload)
    _assert_holdout_policy(payload)
    _assert_holdout_evidence_separation(payload)
    return {"data": payload}


@router.get("/shadow-live-longitudinal")
def get_shadow_live_longitudinal(
    symbol: str | None = Query(None),
    as_of: datetime | None = Query(None),
    horizons: str = Query("7,30,90,180,365"),
) -> dict[str, object]:
    """Measure matured live-shadow predictions without fitting decision rules."""

    effective_as_of = _effective_as_of(as_of)
    effective_horizons = _parse_horizons(horizons)
    try:
        payload = live_longitudinal_service.evaluate(
            as_of=effective_as_of,
            symbol=symbol,
            horizons=effective_horizons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo medir la evidencia longitudinal shadow de ATHENA.",
        ) from exc

    _assert_shadow_contract(payload)
    _assert_longitudinal_policy(payload)
    return {"data": payload}


@router.get("/shadow-live-decision-research")
def get_shadow_live_decision_research(
    candidate_id: int = Query(..., gt=0),
) -> dict[str, object]:
    """Expose immutable live decision diagnostics without advice or action thresholds."""

    try:
        payload = live_decision_research_service.build(candidate_id=candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir decision research shadow de ATHENA.",
        ) from exc

    _assert_shadow_contract(payload)
    _assert_decision_research_policy(payload)
    return {"data": payload}
