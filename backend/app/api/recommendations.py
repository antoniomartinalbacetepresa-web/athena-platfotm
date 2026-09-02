from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)
from app.services.recommendation_fundamental_signal_service import (
    RecommendationFundamentalSignalService,
)
from app.services.recommendation_learning_status_service import (
    RecommendationLearningStatusService,
)
from app.services.recommendation_market_signal_service import (
    RecommendationMarketSignalService,
)
from app.services.recommendation_shadow_temporal_split_service import (
    RecommendationShadowTemporalSplitService,
)
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)


router = APIRouter(
    prefix="/api/v1/recommendations",
    tags=["recommendations"],
)

learning_status_service = RecommendationLearningStatusService()
market_signal_service = RecommendationMarketSignalService()
fundamental_signal_service = RecommendationFundamentalSignalService()
valuation_signal_service = RecommendationValuationSignalService()
evidence_gate_service = RecommendationEvidenceGateService()
temporal_split_service = RecommendationShadowTemporalSplitService()


def _effective_as_of(as_of: datetime | None) -> datetime:
    value = as_of if as_of is not None else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail="as_of debe incluir zona horaria.",
        )
    return value


def _aware_boundary(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field} debe incluir zona horaria.",
        )
    return value


def _diagnostic_payload_or_fail(
    diagnostic: object,
    *,
    diagnostic_name: str,
) -> dict[str, object]:
    to_api_dict = getattr(diagnostic, "to_api_dict", None)
    if not callable(to_api_dict):
        raise HTTPException(
            status_code=500,
            detail=f"El diagnóstico {diagnostic_name} no respeta el contrato de ATHENA.",
        )
    payload = to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"El diagnóstico {diagnostic_name} devolvió un contrato inválido.",
        )
    if payload.get("productionEligible") is not False:
        raise HTTPException(
            status_code=500,
            detail=(
                f"El diagnóstico {diagnostic_name} violó la política de seguridad: "
                "no puede ser productivo antes de la calibración completa."
            ),
        )
    return payload


@router.get("/diagnostics/market-signal")
def get_market_signal_diagnostic(
    symbol: str = Query(
        ...,
        min_length=1,
        description="Símbolo del instrumento que se desea diagnosticar.",
    ),
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte point-in-time. Si se omite se usa la hora UTC actual."
        ),
    ),
) -> dict[str, object]:
    """Return transparent PIT market features without issuing investment advice."""

    effective_as_of = _effective_as_of(as_of)

    try:
        diagnostic = market_signal_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el diagnóstico de mercado de ATHENA.",
        ) from exc

    payload = _diagnostic_payload_or_fail(
        diagnostic,
        diagnostic_name="de mercado",
    )
    return {
        "data": payload,
        "advisoryStatus": "diagnostic_only",
    }


@router.get("/diagnostics/fundamentals")
def get_fundamental_diagnostic(
    symbol: str = Query(
        ...,
        min_length=1,
        description="Símbolo del instrumento que se desea diagnosticar.",
    ),
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte point-in-time. Si se omite se usa la hora UTC actual."
        ),
    ),
) -> dict[str, object]:
    """Return transparent PIT fundamental evidence without issuing advice."""

    effective_as_of = _effective_as_of(as_of)

    try:
        diagnostic = fundamental_signal_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el diagnóstico fundamental de ATHENA.",
        ) from exc

    payload = _diagnostic_payload_or_fail(
        diagnostic,
        diagnostic_name="fundamental",
    )
    return {
        "data": payload,
        "advisoryStatus": "diagnostic_only",
    }


@router.get("/diagnostics/valuation")
def get_valuation_diagnostic(
    symbol: str = Query(
        ...,
        min_length=1,
        description="Símbolo del instrumento cuya valoración PIT se diagnostica.",
    ),
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte point-in-time común al precio y al dato SEC."
        ),
    ),
) -> dict[str, object]:
    """Return a narrow PIT valuation multiple without issuing investment advice."""

    effective_as_of = _effective_as_of(as_of)
    try:
        diagnostic = valuation_signal_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el diagnóstico de valoración de ATHENA.",
        ) from exc

    payload = _diagnostic_payload_or_fail(
        diagnostic,
        diagnostic_name="de valoración",
    )
    return {
        "data": payload,
        "advisoryStatus": "diagnostic_only",
    }


@router.get("/diagnostics/evidence-gate")
def get_evidence_gate_diagnostic(
    symbol: str = Query(
        ...,
        min_length=1,
        description="Símbolo del instrumento cuyo conjunto de evidencia se valida.",
    ),
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte point-in-time común a todos los componentes del gate."
        ),
    ),
) -> dict[str, object]:
    """Return a fail-closed PIT evidence gate without issuing investment advice."""

    effective_as_of = _effective_as_of(as_of)
    try:
        diagnostic = evidence_gate_service.evaluate(
            symbol=symbol,
            as_of=effective_as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el evidence gate de ATHENA.",
        ) from exc

    payload = _diagnostic_payload_or_fail(
        diagnostic,
        diagnostic_name="de evidence gate",
    )
    if payload.get("recommendationCandidateReady") is not False:
        raise HTTPException(
            status_code=500,
            detail=(
                "El evidence gate intentó habilitar una recomendación antes de "
                "completar todas las barreras de validación."
            ),
        )
    return {
        "data": payload,
        "advisoryStatus": "diagnostic_only",
    }


@router.get("/learning/shadow-temporal-split")
def get_shadow_temporal_split(
    train_end: datetime = Query(..., alias="trainEnd"),
    validation_end: datetime = Query(..., alias="validationEnd"),
    as_of: datetime | None = Query(None),
    horizon_days: int | None = Query(None, ge=1, alias="horizonDays"),
    require_benchmark: bool = Query(True, alias="requireBenchmark"),
) -> dict[str, object]:
    """Expose calibration partitions while preserving a strict no-advice contract."""

    effective_as_of = _effective_as_of(as_of)
    effective_train_end = _aware_boundary(train_end, "trainEnd")
    effective_validation_end = _aware_boundary(validation_end, "validationEnd")
    try:
        payload = temporal_split_service.build(
            as_of=effective_as_of,
            train_end=effective_train_end,
            validation_end=effective_validation_end,
            horizon_days=horizon_days,
            require_benchmark=require_benchmark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el split temporal de calibración de ATHENA.",
        ) from exc

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(
            status_code=500,
            detail="El split temporal devolvió una política inválida.",
        )
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(
            status_code=500,
            detail="El split temporal violó el contrato no-advice de ATHENA.",
        )
    if policy.get("productionEligibility") is not False:
        raise HTTPException(
            status_code=500,
            detail="El split temporal no puede habilitar producción.",
        )
    return {"data": payload}


@router.get("/learning/status")
def get_learning_status(
    as_of: datetime | None = Query(
        None,
        description=(
            "Instante de corte del diagnóstico. Si se omite se usa la hora UTC actual."
        ),
    ),
    model_version: str | None = Query(
        None,
        min_length=1,
        alias="modelVersion",
    ),
    horizon_days: int | None = Query(
        None,
        ge=1,
        alias="horizonDays",
    ),
) -> dict[str, object]:
    effective_as_of = _effective_as_of(as_of)

    normalized_model_version = model_version.strip() if model_version is not None else None

    try:
        status = learning_status_service.get_status(
            as_of=effective_as_of,
            model_version=normalized_model_version,
            horizon_days=horizon_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo construir el estado de aprendizaje de ATHENA.",
        ) from exc

    return {
        "data": status,
    }
