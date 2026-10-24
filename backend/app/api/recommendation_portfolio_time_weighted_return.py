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

from app.repositories.recommendation_portfolio_nlv_snapshot_repository import (
    RecommendationPortfolioNlvSnapshotRepository,
)
from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_twr_measurement_repository import (
    RecommendationPortfolioTwrMeasurementRepository,
)
from app.security.portfolio_artifact_ownership import PortfolioArtifactOwnershipRegistry
from app.security.portfolio_owner_storage import owner_scoped_ledger_path
from app.services.recommendation_portfolio_event_ledger_service import (
    RecommendationPortfolioEventLedgerService,
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
_nlv_repository = RecommendationPortfolioNlvSnapshotRepository()
_ownership = PortfolioArtifactOwnershipRegistry()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DEFAULT_LEDGER_PATH = "var/athena/portfolio_event_ledger.jsonl"
_TOTAL_VALUE_SCOPE = "total_net_liquidation_value_in_reporting_currency"
_FINAL_SCHEMA = "athena_portfolio_twr_final_measurement_v1"
_NLV_PAIR_SCHEMA = "athena_portfolio_twr_nlv_pair_v1"


class TwrBoundaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observedAt: datetime
    regularSnapshotKey: str | None = Field(default=None, min_length=64, max_length=64)
    preFlowSnapshotKey: str | None = Field(default=None, min_length=64, max_length=64)
    postFlowSnapshotKey: str | None = Field(default=None, min_length=64, max_length=64)


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
    return owner_scoped_ledger_path(Path(configured))


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


def _nlv_pair_fingerprint(pre_key: str, post_key: str) -> str:
    body = {
        "schema": _NLV_PAIR_SCHEMA,
        "preFlowSnapshotKey": pre_key.lower(),
        "postFlowSnapshotKey": post_key.lower(),
    }
    serialized = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _iso_datetime(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"NLV persistido devolvió {field} inválido.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=500, detail=f"NLV persistido devolvió {field} sin zona horaria.")
    return parsed.astimezone(timezone.utc)


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

    nlv = payload.get("nlvEvidence")
    if not isinstance(nlv, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió evidencia NLV sellada.")
    if nlv.get("callerSuppliedValuesAccepted") is not False or nlv.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Portfolio TWR aceptó valores NLV libres o no verificados.")
    snapshot_keys = nlv.get("snapshotKeys")
    if not isinstance(snapshot_keys, list) or len(snapshot_keys) < 2:
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió snapshotKeys NLV.")
    if any(not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None for key in snapshot_keys):
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió snapshotKey NLV inválida.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR devolvió política inválida.")
    if policy.get("callerSuppliedExternalCashFlowLedger") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR permitió cash-flow ledger del caller.")
    if policy.get("callerSuppliedInternalCashEvents") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR permitió eventos internos del caller.")
    if policy.get("callerSuppliedValuationValues") is not False:
        raise HTTPException(status_code=500, detail="Portfolio TWR permitió valores de valoración del caller.")
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


def _build_boundaries(
    *,
    request: PortfolioTimeWeightedReturnRequest,
    as_of: datetime,
    period_start: datetime,
    period_end: datetime,
    reporting_currency: str,
    ledger_path: Path,
) -> tuple[tuple[PortfolioTwrBoundaryInput, ...], list[str]]:
    ledger = RecommendationPortfolioEventLedgerService(ledger_path)
    external = ledger.external_cash_flows(
        portfolio_id=request.portfolioId,
        reporting_currency=reporting_currency,
        period_start=period_start,
        period_end=period_end,
        as_of=as_of,
    )
    flow_by_time: dict[datetime, float] = {}
    for event in external:
        occurred = event.occurred_at.astimezone(timezone.utc)
        if occurred in flow_by_time:
            raise ValueError("multiple external cash flows at one instant require upstream deterministic aggregation")
        flow_by_time[occurred] = float(event.amount)

    boundaries: list[PortfolioTwrBoundaryInput] = []
    snapshot_keys: list[str] = []
    for index, item in enumerate(request.boundaries):
        observed = _aware_utc(item.observedAt, f"boundaries[{index}].observedAt")
        flow = flow_by_time.get(observed, 0.0)
        regular_key = item.regularSnapshotKey
        pre_key = item.preFlowSnapshotKey
        post_key = item.postFlowSnapshotKey

        if observed in flow_by_time:
            if regular_key is not None or pre_key is None or post_key is None:
                raise ValueError(
                    "external-flow TWR boundary requires preFlowSnapshotKey and postFlowSnapshotKey only"
                )
            pre_record = _nlv_repository.require_snapshot(
                snapshot_key=pre_key,
                portfolio_id=request.portfolioId,
                reporting_currency=reporting_currency,
                observed_at=observed,
                phase="pre_external_flow",
                as_of=as_of,
            )
            post_record = _nlv_repository.require_snapshot(
                snapshot_key=post_key,
                portfolio_id=request.portfolioId,
                reporting_currency=reporting_currency,
                observed_at=observed,
                phase="post_external_flow",
                as_of=as_of,
            )
            pre_artifact = pre_record["artifact"]
            post_artifact = post_record["artifact"]
            pre_value = float(pre_artifact["value"])
            post_value = float(post_artifact["value"])
            available = max(
                _iso_datetime(pre_artifact["availableAt"], "pre.availableAt"),
                _iso_datetime(post_artifact["availableAt"], "post.availableAt"),
            )
            normalized_pre = str(pre_artifact["snapshotKey"]).lower()
            normalized_post = str(post_artifact["snapshotKey"]).lower()
            snapshot_keys.extend((normalized_pre, normalized_post))
            boundaries.append(
                PortfolioTwrBoundaryInput(
                    observed_at=observed,
                    available_at=available,
                    pre_flow_value=pre_value,
                    post_flow_value=post_value,
                    external_flow_amount=flow,
                    currency=reporting_currency,
                    valuation_scope=_TOTAL_VALUE_SCOPE,
                    valuation_fingerprint=_nlv_pair_fingerprint(normalized_pre, normalized_post),
                    source="persisted_portfolio_nlv_snapshot_pair",
                    source_ref=f"{normalized_pre}:{normalized_post}",
                )
            )
            continue

        if regular_key is None or pre_key is not None or post_key is not None:
            raise ValueError("non-flow TWR boundary requires regularSnapshotKey only")
        regular_record = _nlv_repository.require_snapshot(
            snapshot_key=regular_key,
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            observed_at=observed,
            phase="regular",
            as_of=as_of,
        )
        artifact = regular_record["artifact"]
        value = float(artifact["value"])
        normalized_key = str(artifact["snapshotKey"]).lower()
        snapshot_keys.append(normalized_key)
        boundaries.append(
            PortfolioTwrBoundaryInput(
                observed_at=observed,
                available_at=_iso_datetime(artifact["availableAt"], "regular.availableAt"),
                pre_flow_value=value,
                post_flow_value=value,
                external_flow_amount=0.0,
                currency=reporting_currency,
                valuation_scope=_TOTAL_VALUE_SCOPE,
                valuation_fingerprint=normalized_key,
                source=str(artifact["source"]),
                source_ref=str(artifact["sourceRef"]),
            )
        )
    return tuple(boundaries), snapshot_keys


@router.post("/portfolio-time-weighted-return")
def post_portfolio_time_weighted_return(
    request: PortfolioTimeWeightedReturnRequest,
) -> dict[str, object]:
    """Measure and persist TWR from sealed NLV snapshots plus the current owner's canonical ledger."""

    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")
    reporting_currency = request.reportingCurrency.upper()
    if _CURRENCY_RE.fullmatch(reporting_currency) is None:
        raise HTTPException(status_code=400, detail="reportingCurrency debe ser un código ISO de tres letras.")

    try:
        _ownership.require_current_owner(
            artifact_kind="state_reconciliation",
            artifact_key=request.reconciliationKey,
        )
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

    ledger_path = _ledger_path()
    try:
        boundaries, snapshot_keys = _build_boundaries(
            request=request,
            as_of=as_of,
            period_start=period_start,
            period_end=period_end,
            reporting_currency=reporting_currency,
            ledger_path=ledger_path,
        )
        result = RecommendationPortfolioServerSideTwrService(ledger_path=ledger_path).evaluate(
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
            boundaries=boundaries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular Portfolio TWR PIT desde NLV/ledger canónicos.") from exc

    payload = result.to_api_dict()
    payload["nlvEvidence"] = {
        "callerSuppliedValuesAccepted": False,
        "tamperVerified": True,
        "snapshotKeys": snapshot_keys,
        "binding": "regular_or_exact_pre_post_external_flow_snapshots",
    }
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR perdió policy antes del sellado final.")
    policy["callerSuppliedValuationValues"] = False
    policy["valuationEvidence"] = "persisted_tamper_verified_portfolio_nlv_snapshots"
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
