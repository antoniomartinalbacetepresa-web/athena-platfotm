from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.services.recommendation_portfolio_time_weighted_return_service import (
    PortfolioCashFlowEvidence,
    PortfolioTwrSegment,
    PortfolioValueEvidence,
    RecommendationPortfolioTimeWeightedReturnInput,
    RecommendationPortfolioTimeWeightedReturnService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
service = RecommendationPortfolioTimeWeightedReturnService()
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ValueEvidenceRequest(BaseModel):
    value: float
    observedAt: datetime
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class CashFlowEvidenceRequest(BaseModel):
    amount: float
    occurredAt: datetime
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class TwrSegmentRequest(BaseModel):
    startAt: datetime
    endAt: datetime
    beginningValue: ValueEvidenceRequest
    endingValueBeforeFlow: ValueEvidenceRequest
    externalFlowAfterEnd: CashFlowEvidenceRequest | None = None


class PortfolioTimeWeightedReturnRequest(BaseModel):
    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    reconciliationKey: str = Field(min_length=64, max_length=64)
    asOf: datetime
    periodStart: datetime
    periodEnd: datetime
    segments: list[TwrSegmentRequest] = Field(min_length=1, max_length=500)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _value(item: ValueEvidenceRequest, field: str) -> PortfolioValueEvidence:
    return PortfolioValueEvidence(
        value=item.value,
        observed_at=_aware_utc(item.observedAt, f"{field}.observedAt"),
        available_at=_aware_utc(item.availableAt, f"{field}.availableAt"),
        source=item.source,
        source_ref=item.sourceRef,
    )


def _flow(item: CashFlowEvidenceRequest, field: str) -> PortfolioCashFlowEvidence:
    return PortfolioCashFlowEvidence(
        amount=item.amount,
        occurred_at=_aware_utc(item.occurredAt, f"{field}.occurredAt"),
        available_at=_aware_utc(item.availableAt, f"{field}.availableAt"),
        source=item.source,
        source_ref=item.sourceRef,
    )


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=500, detail=f"Portfolio TWR devolvió {field} inválido.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HTTPException(status_code=500, detail=f"Portfolio TWR devolvió {field} no finito.")
    return numeric


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("module") != "portfolio_time_weighted_return":
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Portfolio TWR violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR intentó habilitar producción/weighting.")
    key = payload.get("portfolioReturnKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió identidad inválida.")
    currency = payload.get("reportingCurrency")
    if not isinstance(currency, str) or _CURRENCY_RE.fullmatch(currency) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió moneda inválida.")
    state_integrity = payload.get("stateIntegrity")
    if not isinstance(state_integrity, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió gating de reconciliación.")
    reconciliation_key = state_integrity.get("reconciliationKey")
    if not isinstance(reconciliation_key, str) or _SHA256_RE.fullmatch(reconciliation_key) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió reconciliationKey válido.")
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Portfolio TWR aceptó estado no reconciliado/verificado.")
    if state_integrity.get("gate") != "required_before_measurement":
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió la puerta obligatoria de integridad.")

    twr = _finite(payload.get("timeWeightedReturn"), "timeWeightedReturn")
    _finite(payload.get("netExternalFlow"), "netExternalFlow")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió subperiodos.")
    chain = 1.0
    flow_count = 0
    for segment in segments:
        if not isinstance(segment, dict):
            raise HTTPException(status_code=500, detail="Portfolio TWR devolvió subperiodo inválido.")
        segment_return = _finite(segment.get("segmentReturn"), "segmentReturn")
        chain *= 1.0 + segment_return
        if not math.isfinite(chain):
            raise HTTPException(status_code=500, detail="Portfolio TWR perdió finitud geométrica.")
        if not isinstance(segment.get("beginningValueEvidence"), dict) or not isinstance(
            segment.get("endingValueEvidence"), dict
        ):
            raise HTTPException(status_code=500, detail="Portfolio TWR perdió provenance de valoración.")
        flow = segment.get("externalFlowAfterEnd")
        if flow is not None:
            if not isinstance(flow, dict) or not isinstance(flow.get("evidence"), dict):
                raise HTTPException(status_code=500, detail="Portfolio TWR perdió provenance de cash flow.")
            _finite(flow.get("amount"), "externalFlow.amount")
            flow_count += 1
    if not math.isclose(twr, chain - 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió reconciliación geométrica.")
    if payload.get("externalFlowCount") != flow_count:
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió contador de flujos inconsistente.")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió política inválida.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR intentó habilitar automatización.")
    if policy.get("cashInference") != "forbidden":
        raise HTTPException(status_code=500, detail="Portfolio TWR intentó inferir cash no observado.")


@router.post("/portfolio-time-weighted-return")
def post_portfolio_time_weighted_return(
    request: PortfolioTimeWeightedReturnRequest,
) -> dict[str, object]:
    """Measure historical TWR only after persisted independent state reconciliation."""

    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")
    try:
        reconciliation_record = _reconciliation_repository.require_reconciled(
            reconciliation_key=request.reconciliationKey,
            portfolio_id=request.portfolioId,
            reporting_currency=request.reportingCurrency,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar reconciliationKey para Portfolio TWR.") from exc

    segments: list[PortfolioTwrSegment] = []
    for index, item in enumerate(request.segments):
        start_at = _aware_utc(item.startAt, f"segments[{index}].startAt")
        end_at = _aware_utc(item.endAt, f"segments[{index}].endAt")
        segments.append(
            PortfolioTwrSegment(
                start_at=start_at,
                end_at=end_at,
                beginning_value=_value(item.beginningValue, f"segments[{index}].beginningValue"),
                ending_value_before_flow=_value(
                    item.endingValueBeforeFlow,
                    f"segments[{index}].endingValueBeforeFlow",
                ),
                external_flow_after_end=(
                    _flow(item.externalFlowAfterEnd, f"segments[{index}].externalFlowAfterEnd")
                    if item.externalFlowAfterEnd is not None
                    else None
                ),
            )
        )
    try:
        result = service.evaluate(
            as_of=as_of,
            item=RecommendationPortfolioTimeWeightedReturnInput(
                portfolio_id=request.portfolioId,
                reporting_currency=request.reportingCurrency,
                period_start=period_start,
                period_end=period_end,
                segments=tuple(segments),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular Portfolio TWR PIT.") from exc
    payload = result.to_api_dict()
    payload["stateIntegrity"] = {
        "reconciliationKey": request.reconciliationKey.lower(),
        "portfolioStateKey": reconciliation_record["portfolio_state_key"],
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_measurement",
    }
    _assert_contract(payload)
    return {"data": payload}
