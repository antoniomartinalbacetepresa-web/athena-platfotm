from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_twr_measurement_repository import (
    RecommendationPortfolioTwrMeasurementRepository,
)
from app.repositories.recommendation_reconciled_portfolio_weight_repository import (
    RecommendationReconciledPortfolioWeightRepository,
)
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
)
from app.services.recommendation_portfolio_performance_attribution_service import (
    PortfolioAttributionConstituent,
    RecommendationPortfolioPerformanceAttributionInput,
    RecommendationPortfolioPerformanceAttributionService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
service = RecommendationPortfolioPerformanceAttributionService()
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_twr_repository = RecommendationPortfolioTwrMeasurementRepository()
_weight_repository = RecommendationReconciledPortfolioWeightRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class EvidenceRequest(BaseModel):
    value: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class FactorContributionRequest(BaseModel):
    factor: str = Field(min_length=1)
    contribution: float
    availableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)


class ConstituentAttributionRequest(BaseModel):
    instrumentId: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    instrumentCurrency: str = Field(min_length=3, max_length=3)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    fxPair: str = Field(min_length=7, max_length=7)
    benchmarkId: str = Field(min_length=1)
    totalReturn: EvidenceRequest
    marketContribution: EvidenceRequest
    fxContribution: EvidenceRequest
    factorContributions: list[FactorContributionRequest] = Field(default_factory=list, max_length=20)


class PortfolioConstituentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribution: ConstituentAttributionRequest


class PortfolioPerformanceAttributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    benchmarkId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    measurementKey: str = Field(min_length=64, max_length=64)
    weightEvidenceKey: str = Field(min_length=64, max_length=64)
    asOf: datetime
    periodStart: datetime
    periodEnd: datetime
    constituents: list[PortfolioConstituentRequest] = Field(min_length=1, max_length=200)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _evidence(item: EvidenceRequest, field: str) -> AttributionEvidence:
    return AttributionEvidence(
        value=item.value,
        available_at=_aware_utc(item.availableAt, f"{field}.availableAt"),
        source=item.source,
        source_ref=item.sourceRef,
    )


def _assert_finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=500, detail=f"Portfolio Attribution devolvió {field} inválido.")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise HTTPException(status_code=500, detail=f"Portfolio Attribution devolvió {field} no finito.")
    return numeric


def _require_sealed_nlv_twr(twr_artifact: dict[str, object]) -> list[str]:
    nlv = twr_artifact.get("nlvEvidence")
    if not isinstance(nlv, dict):
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere TWR ligado a snapshots NLV sellados.")
    if nlv.get("callerSuppliedValuesAccepted") is not False:
        raise HTTPException(status_code=400, detail="Portfolio Attribution rechaza TWR con valores NLV aportados por el caller.")
    if nlv.get("tamperVerified") is not True:
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere evidencia NLV tamper-verified.")
    if nlv.get("binding") != "regular_or_exact_pre_post_external_flow_snapshots":
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere binding NLV canónico.")
    keys = nlv.get("snapshotKeys")
    if not isinstance(keys, list) or len(keys) < 2:
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere snapshotKeys NLV persistidas.")
    normalized: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if not isinstance(key, str) or _SHA256_RE.fullmatch(key.lower()) is None:
            raise HTTPException(status_code=400, detail="Portfolio Attribution recibió snapshotKey NLV inválida.")
        normalized_key = key.lower()
        if normalized_key in seen:
            raise HTTPException(status_code=400, detail="Portfolio Attribution recibió snapshotKey NLV duplicada.")
        seen.add(normalized_key)
        normalized.append(normalized_key)
    policy = twr_artifact.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=400, detail="Portfolio TWR persistido perdió policy.")
    if policy.get("callerSuppliedValuationValues") is not False:
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere prohibición explícita de valores de valoración del caller.")
    if policy.get("valuationEvidence") != "persisted_tamper_verified_portfolio_nlv_snapshots":
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere valoración desde snapshots NLV persistidos.")
    return normalized


def _canonical_weight_map(
    *,
    record: dict[str, object],
    weight_evidence_key: str,
    period_start: datetime,
) -> tuple[dict[str, AttributionEvidence], dict[str, object]]:
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Weight evidence persistida carece de artifact válido.")
    cash_weight = _assert_finite(artifact.get("cashWeight"), "weightEvidence.cashWeight")
    if not math.isclose(cash_weight, 0.0, rel_tol=0.0, abs_tol=1e-12):
        raise HTTPException(
            status_code=400,
            detail="Portfolio Attribution no admite cash inicial distinto de cero hasta disponer de atribución explícita de cash.",
        )
    positions = artifact.get("positions")
    if not isinstance(positions, list) or not positions:
        raise HTTPException(status_code=400, detail="Weight evidence no contiene posiciones atribuibles.")
    weights: dict[str, AttributionEvidence] = {}
    for index, item in enumerate(positions):
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail="Weight evidence contiene posición inválida.")
        instrument_raw = item.get("instrumentId")
        if isinstance(instrument_raw, bool) or not isinstance(instrument_raw, int) or instrument_raw <= 0:
            raise HTTPException(status_code=500, detail="Weight evidence perdió identidad canónica de instrumento.")
        instrument_id = str(instrument_raw)
        if instrument_id in weights:
            raise HTTPException(status_code=500, detail="Weight evidence contiene instrumento duplicado.")
        weight = _assert_finite(item.get("weight"), f"weightEvidence.positions[{index}].weight")
        if weight <= 0.0 or weight > 1.0:
            raise HTTPException(status_code=400, detail="Weight evidence contiene ponderación no positiva/inválida.")
        weights[instrument_id] = AttributionEvidence(
            value=weight,
            available_at=period_start,
            source="athena_persisted_reconciled_portfolio_weights",
            source_ref=f"weight-evidence:{weight_evidence_key.lower()}:{instrument_id}",
        )
    if not math.isclose(sum(item.value for item in weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise HTTPException(status_code=500, detail="Weight evidence sin cash no reconcilia a 1.0.")
    binding = {
        "weightEvidenceKey": weight_evidence_key.lower(),
        "reconciliationKey": artifact.get("reconciliationKey"),
        "portfolioStateKey": artifact.get("portfolioStateKey"),
        "portfolioValuationEvidenceFingerprint": artifact.get("portfolioValuationEvidenceFingerprint"),
        "cashWeight": cash_weight,
        "tamperVerified": True,
        "callerSuppliedWeightsAccepted": False,
        "gate": "required_before_attribution",
    }
    for field in ("reconciliationKey", "portfolioStateKey", "portfolioValuationEvidenceFingerprint"):
        value = binding.get(field)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value.lower()) is None:
            raise HTTPException(status_code=500, detail=f"Weight evidence perdió {field} válido.")
    return weights, binding


def _assert_contract(payload: dict[str, object], measurement_key: str, weight_evidence_key: str) -> None:
    if payload.get("module") != "portfolio_performance_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Portfolio Attribution violó no_advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution intentó habilitar weighting.")

    key = payload.get("portfolioAttributionKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió identidad inválida.")
    currency = payload.get("reportingCurrency")
    if not isinstance(currency, str) or _CURRENCY_RE.fullmatch(currency) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió moneda inválida.")

    measurement = payload.get("performanceMeasurement")
    if not isinstance(measurement, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió binding de TWR.")
    if measurement.get("measurementKey") != measurement_key.lower():
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió measurementKey sellada.")
    if measurement.get("tamperVerified") is not True or measurement.get("gate") != "required_before_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó medición TWR no verificada.")
    ledger_key = measurement.get("ledgerMeasurementKey")
    ledger_head = measurement.get("ledgerHeadHash")
    if not isinstance(ledger_key, str) or _SHA256_RE.fullmatch(ledger_key) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió ledgerMeasurementKey.")
    if not isinstance(ledger_head, str) or _SHA256_RE.fullmatch(ledger_head) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió ledgerHeadHash.")
    nlv_keys = measurement.get("nlvSnapshotKeys")
    if not isinstance(nlv_keys, list) or len(nlv_keys) < 2:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió snapshotKeys NLV.")
    if any(not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in nlv_keys):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió snapshotKeys NLV inválidas.")

    weight_binding = payload.get("weightEvidence")
    if not isinstance(weight_binding, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió binding de pesos canónicos.")
    if weight_binding.get("weightEvidenceKey") != weight_evidence_key.lower():
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió weightEvidenceKey sellada.")
    if weight_binding.get("tamperVerified") is not True or weight_binding.get("callerSuppliedWeightsAccepted") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution volvió a aceptar pesos libres.")
    if weight_binding.get("gate") != "required_before_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió gate de pesos canónicos.")
    if not math.isclose(_assert_finite(weight_binding.get("cashWeight"), "weightEvidence.cashWeight"), 0.0, rel_tol=0.0, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó cash no atribuido.")

    state_integrity = payload.get("stateIntegrity")
    if not isinstance(state_integrity, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió gating de reconciliación.")
    reconciliation_key = state_integrity.get("reconciliationKey")
    if not isinstance(reconciliation_key, str) or _SHA256_RE.fullmatch(reconciliation_key) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió reconciliationKey válido.")
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó estado no reconciliado/verificado.")
    if state_integrity.get("gate") != "required_before_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió la puerta obligatoria de integridad.")
    if measurement.get("reconciliationKey") != reconciliation_key:
        raise HTTPException(status_code=500, detail="Portfolio Attribution mezcló medición y reconciliación distintas.")

    observed = _assert_finite(payload.get("observedPortfolioReturn"), "observedPortfolioReturn")
    reconstructed = _assert_finite(payload.get("reconstructedPortfolioReturn"), "reconstructedPortfolioReturn")
    reconciliation_error = _assert_finite(payload.get("reconciliationError"), "reconciliationError")
    market = _assert_finite(payload.get("marketContribution"), "marketContribution")
    fx = _assert_finite(payload.get("fxContribution"), "fxContribution")
    explained = _assert_finite(payload.get("explainedReturn"), "explainedReturn")
    residual = _assert_finite(payload.get("residualReturn"), "residualReturn")

    factors = payload.get("factorContributions")
    if not isinstance(factors, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió factores inválidos.")
    factor_sum = sum(_assert_finite(value, f"factorContributions.{name}") for name, value in factors.items())
    if not math.isclose(observed, reconstructed + reconciliation_error, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió reconciliación de retorno.")
    if not math.isclose(explained, market + fx + factor_sum, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió explainedReturn inconsistente.")
    if not math.isclose(observed, explained + residual, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió residual inconsistente.")

    constituents = payload.get("constituents")
    if not isinstance(constituents, list) or not constituents:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió constituyentes.")
    seen_instruments: set[str] = set()
    seen_keys: set[str] = set()
    weight_sum = 0.0
    for constituent in constituents:
        if not isinstance(constituent, dict):
            raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió constituyente inválido.")
        instrument_id = constituent.get("instrumentId")
        child_key = constituent.get("attributionKey")
        if not isinstance(instrument_id, str) or not instrument_id:
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió identidad de instrumento.")
        if instrument_id in seen_instruments:
            raise HTTPException(status_code=500, detail="Portfolio Attribution duplicó instrumento.")
        if not isinstance(child_key, str) or _SHA256_RE.fullmatch(child_key) is None or child_key in seen_keys:
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió identidad de atribución hija.")
        seen_instruments.add(instrument_id)
        seen_keys.add(child_key)
        weight_sum += _assert_finite(constituent.get("weight"), "constituent.weight")
        weight_evidence = constituent.get("weightEvidence")
        if not isinstance(weight_evidence, dict):
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió provenance de pesos.")
        expected_ref = f"weight-evidence:{weight_evidence_key.lower()}:{instrument_id}"
        if weight_evidence.get("source") != "athena_persisted_reconciled_portfolio_weights" or weight_evidence.get("sourceRef") != expected_ref:
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió trazabilidad de peso sellado.")
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió pesos inconsistentes.")

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or "observedPortfolioReturn" not in evidence:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió provenance.")
    observed_evidence = evidence["observedPortfolioReturn"]
    if not isinstance(observed_evidence, dict) or observed_evidence.get("sourceRef") != f"twr:{measurement_key.lower()}":
        raise HTTPException(status_code=500, detail="Portfolio Attribution no trazó el retorno a la medición TWR.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió política inválida.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution intentó habilitar automatización.")
    if policy.get("residualInterpretation") != "unexplained_not_automatic_stock_selection_alpha":
        raise HTTPException(status_code=500, detail="Portfolio Attribution interpretó residual como alpha.")
    if policy.get("weighting") != "historical_beginning_weights_diagnostic_only":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió límite de weighting.")
    if policy.get("weightEvidence") != "persisted_tamper_verified_reconciled_beginning_weights_required":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió requisito de pesos históricos sellados.")
    if policy.get("cashAttribution") != "nonzero_beginning_cash_blocked_until_explicit_cash_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió límite de atribución de cash.")
    if policy.get("cashFlows") != "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió tratamiento seguro de cash flows.")
    if policy.get("observedReturn") != "sealed_portfolio_twr_measurement_required":
        raise HTTPException(status_code=500, detail="Portfolio Attribution volvió a aceptar retorno observado libre.")
    if policy.get("valuationEvidence") != "sealed_portfolio_twr_nlv_snapshots_required":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió requisito de NLV sellado.")


@router.post("/portfolio-performance-attribution")
def post_portfolio_performance_attribution(
    request: PortfolioPerformanceAttributionRequest,
) -> dict[str, object]:
    """Reconcile attribution from sealed TWR plus persisted beginning weight evidence."""

    as_of = _aware_utc(request.asOf, "asOf")
    period_start = _aware_utc(request.periodStart, "periodStart")
    period_end = _aware_utc(request.periodEnd, "periodEnd")
    reporting_currency = request.reportingCurrency.upper()

    try:
        twr_record = _twr_repository.require_measurement(
            measurement_key=request.measurementKey,
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar measurementKey para Portfolio Attribution.") from exc

    twr_artifact = twr_record["artifact"]
    if not isinstance(twr_artifact, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR persistido carece de artifact válido.")
    nlv_snapshot_keys = _require_sealed_nlv_twr(twr_artifact)
    state = twr_artifact.get("stateIntegrity")
    ledger = twr_artifact.get("serverSideLedger")
    if not isinstance(state, dict) or not isinstance(ledger, dict):
        raise HTTPException(status_code=500, detail="Portfolio TWR persistido perdió integridad de estado/ledger.")
    reconciliation_key = str(state.get("reconciliationKey") or "")

    try:
        reconciliation_record = _reconciliation_repository.require_reconciled(
            reconciliation_key=reconciliation_key,
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            as_of=as_of,
        )
        weight_record = _weight_repository.require_weight_evidence(
            weight_evidence_key=request.weightEvidenceKey,
            portfolio_id=request.portfolioId,
            reporting_currency=reporting_currency,
            as_of=period_start,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron reverificar reconciliación/pesos históricos para Portfolio Attribution.",
        ) from exc

    canonical_weights, weight_binding = _canonical_weight_map(
        record=weight_record,
        weight_evidence_key=request.weightEvidenceKey,
        period_start=period_start,
    )
    requested_ids = [item.attribution.instrumentId for item in request.constituents]
    if any(not value.isdigit() or str(int(value)) != value or int(value) <= 0 for value in requested_ids):
        raise HTTPException(status_code=400, detail="Portfolio Attribution requiere instrumentId canónico entero positivo.")
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(status_code=400, detail="Portfolio Attribution recibió instrumentId duplicado.")
    if set(requested_ids) != set(canonical_weights):
        missing = sorted(set(canonical_weights) - set(requested_ids))
        extra = sorted(set(requested_ids) - set(canonical_weights))
        raise HTTPException(
            status_code=400,
            detail=f"Portfolio Attribution debe usar exactamente los instrumentos de weight evidence; missing={missing}, extra={extra}.",
        )

    observed_return = _assert_finite(twr_artifact.get("timeWeightedReturn"), "persistedTwr.timeWeightedReturn")
    observed_evidence = AttributionEvidence(
        value=observed_return,
        available_at=as_of,
        source="athena_persisted_portfolio_twr",
        source_ref=f"twr:{request.measurementKey.lower()}",
    )

    constituents: list[PortfolioAttributionConstituent] = []
    for index, item in enumerate(request.constituents):
        child = item.attribution
        factors = tuple(
            FactorContributionEvidence(
                factor=factor.factor,
                contribution=factor.contribution,
                available_at=_aware_utc(
                    factor.availableAt,
                    f"constituents[{index}].attribution.factorContributions.availableAt",
                ),
                source=factor.source,
                source_ref=factor.sourceRef,
            )
            for factor in child.factorContributions
        )
        constituents.append(
            PortfolioAttributionConstituent(
                weight=canonical_weights[child.instrumentId],
                attribution=RecommendationPerformanceAttributionInput(
                    instrument_id=child.instrumentId,
                    symbol=child.symbol,
                    instrument_currency=child.instrumentCurrency,
                    reporting_currency=child.reportingCurrency,
                    fx_pair=child.fxPair,
                    benchmark_id=child.benchmarkId,
                    period_start=period_start,
                    period_end=period_end,
                    total_return=_evidence(child.totalReturn, f"constituents[{index}].attribution.totalReturn"),
                    market_contribution=_evidence(child.marketContribution, f"constituents[{index}].attribution.marketContribution"),
                    fx_contribution=_evidence(child.fxContribution, f"constituents[{index}].attribution.fxContribution"),
                    factor_contributions=factors,
                ),
            )
        )

    try:
        result = service.evaluate(
            as_of=as_of,
            item=RecommendationPortfolioPerformanceAttributionInput(
                portfolio_id=request.portfolioId,
                benchmark_id=request.benchmarkId,
                reporting_currency=reporting_currency,
                period_start=period_start,
                period_end=period_end,
                observed_portfolio_return=observed_evidence,
                constituents=tuple(constituents),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo calcular Portfolio Performance Attribution PIT.") from exc

    payload = result.to_api_dict()
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió política inválida.")
    policy["cashFlows"] = "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated"
    policy["observedReturn"] = "sealed_portfolio_twr_measurement_required"
    policy["valuationEvidence"] = "sealed_portfolio_twr_nlv_snapshots_required"
    policy["weightEvidence"] = "persisted_tamper_verified_reconciled_beginning_weights_required"
    policy["cashAttribution"] = "nonzero_beginning_cash_blocked_until_explicit_cash_attribution"
    payload["performanceMeasurement"] = {
        "measurementKey": request.measurementKey.lower(),
        "ledgerMeasurementKey": twr_artifact["ledgerMeasurementKey"],
        "ledgerHeadHash": ledger["ledgerHeadHash"],
        "reconciliationKey": reconciliation_key,
        "nlvSnapshotKeys": nlv_snapshot_keys,
        "tamperVerified": True,
        "gate": "required_before_attribution",
    }
    payload["weightEvidence"] = weight_binding
    payload["stateIntegrity"] = {
        "reconciliationKey": reconciliation_key,
        "portfolioStateKey": reconciliation_record["portfolio_state_key"],
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_attribution",
    }
    _assert_contract(payload, request.measurementKey, request.weightEvidenceKey)
    return {"data": payload}
