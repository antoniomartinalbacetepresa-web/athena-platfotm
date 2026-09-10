from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_twr_measurement_repository import (
    RecommendationPortfolioTwrMeasurementRepository,
)
from app.services.recommendation_portfolio_server_side_twr_service import (
    RecommendationPortfolioServerSideTwrService,
)
from app.services.recommendation_portfolio_twr_measurement_service import PortfolioTwrBoundaryInput


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_measurement_repository = RecommendationPortfolioTwrMeasurementRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DEFAULT_LEDGER_PATH = "var/athena/portfolio_event_ledger.jsonl"
_TOTAL_VALUE_SCOPE = "total_net_liquidation_value_in_reporting_currency"
_FINAL_SCHEMA = "athena_portfolio_twr_final_measurement_v1"


class TwrBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observedAt: datetime
    availableAt: datetime
    preFlowValue: float
    postFlowValue: float
    externalFlowAmount: float = 0.0
    currency: str = Field(min_length=3, max_length=3)
    valuationScope: str = Field(min_length=1)
    valuationFingerprint: str = Field(min_length=64, max_length=64)
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class PortfolioTimeWeightedReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    reconciliationKey: str = Field(min_length=64, max_length=64)
    asOf: datetime
    periodStart: datetime
    periodEnd: datetime
    boundaries: list[TwrBoundaryRequest] = Field(min_length=2, max_length=2000)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _ledger_path() -> Path:
    configured = os.environ.get("ATHENA_PORTFOLIO_EVENT_LEDGER_PATH", _DEFAULT_LEDGER_PATH).strip()
    if not configured:
        raise HTTPException(status_code=503, detail="Portfolio event ledger no tiene ruta de persistencia configurada.")
    return Path(configured)


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=500, detail=f"Portfolio TWR devolvió {field} inválido.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HTTPException(status_code=500, detail=f"Portfolio TWR devolvió {field} no finito.")
    return numeric


def _final_identity(payload: dict[str, object]) -> str:
    identity = dict(payload)
    identity.pop("measurementKey", None)
    identity["finalMeasurementSchema"] = _FINAL_SCHEMA
    try:
        return json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Portfolio TWR final contiene datos no serializables/no finitos.") from exc


def _seal_final_measurement(payload: dict[str, object]) -> None:
    ledger_key = payload.get("measurementKey")
    if not isinstance(ledger_key, str) or _SHA256_RE.fullmatch(ledger_key) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió measurementKey ledger-bound.")
    payload["ledgerMeasurementKey"] = ledger_key
    payload["measurementKey"] = hashlib.sha256(_final_identity(payload).encode("utf-8")).hexdigest()


def _assert_contract(payload: dict[str, object], reconciliation_key: str) -> None:
    if payload.get("module") != "portfolio_twr_measurement":
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió módulo inválido.")
    if payload.get("status") != "measured_from_canonical_server_side_portfolio_ledger":
        raise HTTPException(status_code=500, detail="Portfolio TWR no usó el ledger canónico server-side.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Portfolio TWR violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR intentó habilitar producción/weighting.")

    measurement_key = payload.get("measurementKey")
    ledger_key = payload.get("ledgerMeasurementKey")
    core_key = payload.get("coreMeasurementKey")
    for value, field in (
        (measurement_key, "measurementKey"),
        (ledger_key, "ledgerMeasurementKey"),
        (core_key, "coreMeasurementKey"),
    ):
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise HTTPException(status_code=500, detail=f"Portfolio TWR devolvió {field} inválido.")
    if measurement_key != hashlib.sha256(_final_identity(payload).encode("utf-8")).hexdigest():
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió sellado final contra reconciliación/ledger.")
    _finite(payload.get("timeWeightedReturn"), "timeWeightedReturn")
    _finite(payload.get("externalFlowTotal"), "externalFlowTotal")

    currency = payload.get("reportingCurrency")
    if not isinstance(currency, str) or _CURRENCY_RE.fullmatch(currency) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió moneda inválida.")

    server_ledger = payload.get("serverSideLedger")
    if not isinstance(server_ledger, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió evidencia de ledger server-side.")
    if server_ledger.get("serverSide") is not True:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió marca server-side explícita.")
    if server_ledger.get("callerSuppliedEventsAccepted") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR aceptó eventos de cartera del caller.")
    if server_ledger.get("appendOnly") is not True or server_ledger.get("tamperEvidentHashChain") is not True:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió integridad append-only del ledger.")
    ledger_head = server_ledger.get("ledgerHeadHash")
    if not isinstance(ledger_head, str) or _SHA256_RE.fullmatch(ledger_head) is None:
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió ledgerHeadHash inválido.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió política inválida.")
    if policy.get("callerSuppliedExternalCashFlowLedger") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR permitió cash-flow ledger del caller.")
    if policy.get("callerSuppliedInternalCashEvents") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR permitió eventos internos del caller.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR intentó habilitar automatización.")
    if policy.get("valuationScope") != _TOTAL_VALUE_SCOPE:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió alcance de NLV total.")

    state_integrity = payload.get("stateIntegrity")
    if not isinstance(state_integrity, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió gating de reconciliación.")
    if state_integrity.get("reconciliationKey") != reconciliation_key.lower():
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió binding de reconciliationKey.")
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Portfolio TWR aceptó estado no reconciliado/verificado.")
    if state_integrity.get("gate") != "required_before_measurement":
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió la puerta obligatoria de integridad.")


@router.post("/portfolio-time-weighted-return")
def post_portfolio_time_weighted_return(
    request: PortfolioTimeWeightedReturnRequest,
) -> dict[str, object]:
    """Measure and persist TWR from total-NLV PIT boundaries plus canonical server ledger."""

    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")
    reporting_currency = request.reportingCurrency.upper()
    if _CURRENCY_RE.fullmatch(reporting_currency) is None:
        raise HTTPException(status_code=400, detail="reportingCurrency debe ser un código ISO de tres letras.")

    try:
        reconciliation_record = _reconciliation_repository.require_reconciled(
            reconciliation_key=request.reconciliationKey,
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar reconciliationKey para Portfolio TWR.") from exc

    boundaries = tuple(
        PortfolioTwrBoundaryInput(
            observed_at=_aware_utc(item.observedAt, f"boundaries[{index}].observedAt"),
            available_at=_aware_utc(item.availableAt, f"boundaries[{index}].availableAt"),
            pre_flow_value=item.preFlowValue,
            post_flow_value=item.postFlowValue,
            external_flow_amount=item.externalFlowAmount,
            currency=item.currency,
            valuation_scope=item.valuationScope,
            valuation_fingerprint=item.valuationFingerprint,
            source=item.source,
            source_ref=item.sourceRef,
        )
        for index, item in enumerate(request.boundaries)
    )

    try:
        result = RecommendationPortfolioServerSideTwrService(ledger_path=_ledger_path()).evaluate(
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            boundaries=boundaries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular Portfolio TWR PIT desde el ledger canónico.") from exc

    payload = result.to_api_dict()
    payload["stateIntegrity"] = {
        "reconciliationKey": request.reconciliationKey.lower(),
        "portfolioStateKey": reconciliation_record["portfolio_state_key"],
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_measurement",
    }
    _seal_final_measurement(payload)
    _assert_contract(payload, request.reconciliationKey)
    try:
        record = _measurement_repository.append(artifact=payload)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo persistir Portfolio TWR sellado: {exc}") from exc
    return {
        "data": payload,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }


@router.get("/portfolio-time-weighted-return/{measurement_key}")
def get_portfolio_time_weighted_return(measurement_key: str) -> dict[str, object]:
    """Read a previously persisted final TWR measurement after tamper verification."""

    try:
        record = _measurement_repository.get_by_key(measurement_key=measurement_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    artifact = record["artifact"]
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR persistido carece de artifact válido.")
    state = artifact.get("stateIntegrity")
    if not isinstance(state, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR persistido perdió stateIntegrity.")
    _assert_contract(artifact, str(state.get("reconciliationKey") or ""))
    return {
        "data": artifact,
        "persistence": {
            "appendOnly": True,
            "tamperVerified": True,
            "artifactHash": record["artifact_hash"],
        },
    }
