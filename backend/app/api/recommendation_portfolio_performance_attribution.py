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
    weight: EvidenceRequest
    attribution: ConstituentAttributionRequest


class PortfolioPerformanceAttributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    benchmarkId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    measurementKey: str = Field(min_length=64, max_length=64)
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


def _assert_contract(payload: dict[str, object], measurement_key: str) -> None:
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
        if not isinstance(constituent.get("weightEvidence"), dict):
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió provenance de pesos.")
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
    if policy.get("cashFlows") != "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated":
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió tratamiento seguro de cash flows.")
    if policy.get("observedReturn") != "sealed_portfolio_twr_measurement_required":
        raise HTTPException(status_code=500, detail="Portfolio Attribution volvió a aceptar retorno observado libre.")


@router.post("/portfolio-performance-attribution")
def post_portfolio_performance_attribution(
    request: PortfolioPerformanceAttributionRequest,
) -> dict[str, object]:
    """Reconcile attribution against a persisted, tamper-verified portfolio TWR measurement."""

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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo reverificar reconciliación de la medición TWR para Portfolio Attribution.",
        ) from exc

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
                weight=_evidence(item.weight, f"constituents[{index}].weight"),
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
    payload["performanceMeasurement"] = {
        "measurementKey": request.measurementKey.lower(),
        "ledgerMeasurementKey": twr_artifact["ledgerMeasurementKey"],
        "ledgerHeadHash": ledger["ledgerHeadHash"],
        "reconciliationKey": reconciliation_key,
        "tamperVerified": True,
        "gate": "required_before_attribution",
    }
    payload["stateIntegrity"] = {
        "reconciliationKey": reconciliation_key,
        "portfolioStateKey": reconciliation_record["portfolio_state_key"],
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_attribution",
    }
    _assert_contract(payload, request.measurementKey)
    return {"data": payload}
