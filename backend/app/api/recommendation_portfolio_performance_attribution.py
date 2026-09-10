from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_performance_attribution_repository import (
    RecommendationPerformanceAttributionRepository,
)
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
_attribution_repository = RecommendationPerformanceAttributionRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class PortfolioConstituentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributionKey: str = Field(min_length=64, max_length=64)


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


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=500, detail=f"{field} persistido inválido.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"{field} persistido inválido.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=500, detail=f"{field} persistido carece de zona horaria.")
    return parsed.astimezone(timezone.utc)


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
    *, record: dict[str, object], weight_evidence_key: str, period_start: datetime
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


def _evidence_from_artifact(
    *, artifact: dict[str, object], evidence: dict[str, object], evidence_name: str, value_name: str
) -> AttributionEvidence:
    meta = evidence.get(evidence_name)
    if not isinstance(meta, dict):
        raise HTTPException(status_code=500, detail=f"Attribution persistida perdió evidence.{evidence_name}.")
    source = meta.get("source")
    source_ref = meta.get("sourceRef")
    if not isinstance(source, str) or not source or not isinstance(source_ref, str) or not source_ref:
        raise HTTPException(status_code=500, detail="Attribution persistida perdió provenance.")
    return AttributionEvidence(
        value=_assert_finite(artifact.get(value_name), value_name),
        available_at=_parse_utc(meta.get("availableAt"), f"evidence.{evidence_name}.availableAt"),
        source=source,
        source_ref=source_ref,
    )


def _persisted_child_input(
    *, record: dict[str, object], benchmark_id: str, reporting_currency: str,
    period_start: datetime, period_end: datetime, as_of: datetime
) -> RecommendationPerformanceAttributionInput:
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Performance Attribution persistida carece de artifact válido.")
    currency = artifact.get("currency")
    evidence = artifact.get("evidence")
    factor_values = artifact.get("factorContributions")
    if not isinstance(currency, dict) or not isinstance(evidence, dict) or not isinstance(factor_values, dict):
        raise HTTPException(status_code=500, detail="Performance Attribution persistida perdió currency/evidence/factors.")
    if artifact.get("benchmarkId") != benchmark_id:
        raise HTTPException(status_code=400, detail="Performance Attribution hija usa otro benchmark.")
    if currency.get("reportingCurrency") != reporting_currency:
        raise HTTPException(status_code=400, detail="Performance Attribution hija usa otra moneda de reporting.")
    if _parse_utc(artifact.get("periodStart"), "child.periodStart") != period_start:
        raise HTTPException(status_code=400, detail="Performance Attribution hija usa otro periodStart.")
    if _parse_utc(artifact.get("periodEnd"), "child.periodEnd") != period_end:
        raise HTTPException(status_code=400, detail="Performance Attribution hija usa otro periodEnd.")
    if _parse_utc(artifact.get("asOf"), "child.asOf") != as_of:
        raise HTTPException(status_code=400, detail="Performance Attribution hija usa otro asOf.")

    factor_meta = evidence.get("factorContributions")
    if not isinstance(factor_meta, dict) or set(factor_meta) != set(factor_values):
        raise HTTPException(status_code=500, detail="Performance Attribution hija perdió provenance factorial exacta.")
    factors: list[FactorContributionEvidence] = []
    for name in sorted(factor_values):
        meta = factor_meta.get(name)
        if not isinstance(meta, dict):
            raise HTTPException(status_code=500, detail="Performance Attribution hija perdió provenance factorial.")
        source = meta.get("source")
        source_ref = meta.get("sourceRef")
        if not isinstance(source, str) or not source or not isinstance(source_ref, str) or not source_ref:
            raise HTTPException(status_code=500, detail="Performance Attribution hija perdió provenance factorial.")
        factors.append(
            FactorContributionEvidence(
                factor=str(name),
                contribution=_assert_finite(factor_values[name], f"factorContributions.{name}"),
                available_at=_parse_utc(meta.get("availableAt"), f"factorContributions.{name}.availableAt"),
                source=source,
                source_ref=source_ref,
            )
        )

    instrument_id = str(artifact.get("instrumentId") or "")
    if not instrument_id.isdigit() or str(int(instrument_id)) != instrument_id or int(instrument_id) <= 0:
        raise HTTPException(status_code=400, detail="Performance Attribution hija requiere instrumentId canónico entero positivo.")
    instrument_currency = currency.get("instrumentCurrency")
    fx_pair = currency.get("fxPair")
    symbol = artifact.get("symbol")
    if not isinstance(instrument_currency, str) or not isinstance(fx_pair, str) or not isinstance(symbol, str) or not symbol:
        raise HTTPException(status_code=500, detail="Performance Attribution hija perdió identidad/FX.")
    return RecommendationPerformanceAttributionInput(
        instrument_id=instrument_id,
        symbol=symbol,
        instrument_currency=instrument_currency,
        reporting_currency=reporting_currency,
        fx_pair=fx_pair,
        benchmark_id=benchmark_id,
        period_start=period_start,
        period_end=period_end,
        total_return=_evidence_from_artifact(
            artifact=artifact, evidence=evidence, evidence_name="totalReturn", value_name="totalReturn"
        ),
        market_contribution=_evidence_from_artifact(
            artifact=artifact, evidence=evidence, evidence_name="marketContribution", value_name="marketContribution"
        ),
        fx_contribution=_evidence_from_artifact(
            artifact=artifact, evidence=evidence, evidence_name="fxContribution", value_name="fxContribution"
        ),
        factor_contributions=tuple(factors),
    )


def _assert_contract(
    payload: dict[str, object], measurement_key: str, weight_evidence_key: str,
    attribution_keys: list[str]
) -> None:
    if payload.get("module") != "portfolio_performance_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió módulo inválido.")
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Portfolio Attribution violó no_advice.")
    if payload.get("productionEligible") is not False or payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution intentó habilitar producción/weighting.")
    key = payload.get("portfolioAttributionKey")
    if not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió identidad inválida.")
    currency = payload.get("reportingCurrency")
    if not isinstance(currency, str) or _CURRENCY_RE.fullmatch(currency) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió moneda inválida.")

    measurement = payload.get("performanceMeasurement")
    if not isinstance(measurement, dict) or measurement.get("measurementKey") != measurement_key.lower():
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió measurementKey sellada.")
    if measurement.get("tamperVerified") is not True or measurement.get("gate") != "required_before_attribution":
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó medición TWR no verificada.")
    for name in ("ledgerMeasurementKey", "ledgerHeadHash"):
        value = measurement.get(name)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise HTTPException(status_code=500, detail=f"Portfolio Attribution perdió {name}.")
    nlv_keys = measurement.get("nlvSnapshotKeys")
    if not isinstance(nlv_keys, list) or len(nlv_keys) < 2 or any(
        not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in nlv_keys
    ):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió snapshotKeys NLV.")

    weight_binding = payload.get("weightEvidence")
    if not isinstance(weight_binding, dict) or weight_binding.get("weightEvidenceKey") != weight_evidence_key.lower():
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió weightEvidenceKey sellada.")
    if weight_binding.get("tamperVerified") is not True or weight_binding.get("callerSuppliedWeightsAccepted") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution volvió a aceptar pesos libres.")
    if not math.isclose(_assert_finite(weight_binding.get("cashWeight"), "weightEvidence.cashWeight"), 0.0, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó cash no atribuido.")

    child_binding = payload.get("childAttributionEvidence")
    if not isinstance(child_binding, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió binding de atribuciones hijas.")
    if child_binding.get("tamperVerified") is not True or child_binding.get("callerSuppliedChildAttributionsAccepted") is not False:
        raise HTTPException(status_code=500, detail="Portfolio Attribution volvió a aceptar atribuciones hijas libres.")
    if child_binding.get("attributionKeys") != attribution_keys:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió attributionKeys hijas.")

    state = payload.get("stateIntegrity")
    if not isinstance(state, dict) or state.get("reconciled") is not True or state.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Portfolio Attribution aceptó estado no reconciliado/verificado.")
    reconciliation_key = state.get("reconciliationKey")
    if not isinstance(reconciliation_key, str) or _SHA256_RE.fullmatch(reconciliation_key) is None:
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió reconciliationKey.")
    if measurement.get("reconciliationKey") != reconciliation_key:
        raise HTTPException(status_code=500, detail="Portfolio Attribution mezcló medición y reconciliación TWR distintas.")

    observed = _assert_finite(payload.get("observedPortfolioReturn"), "observedPortfolioReturn")
    reconstructed = _assert_finite(payload.get("reconstructedPortfolioReturn"), "reconstructedPortfolioReturn")
    error = _assert_finite(payload.get("reconciliationError"), "reconciliationError")
    market = _assert_finite(payload.get("marketContribution"), "marketContribution")
    fx = _assert_finite(payload.get("fxContribution"), "fxContribution")
    explained = _assert_finite(payload.get("explainedReturn"), "explainedReturn")
    residual = _assert_finite(payload.get("residualReturn"), "residualReturn")
    factors = payload.get("factorContributions")
    if not isinstance(factors, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió factores inválidos.")
    factor_sum = sum(_assert_finite(value, f"factorContributions.{name}") for name, value in factors.items())
    if not math.isclose(observed, reconstructed + error, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió reconciliación de retorno.")
    if not math.isclose(explained, market + fx + factor_sum, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió explainedReturn inconsistente.")
    if not math.isclose(observed, explained + residual, rel_tol=1e-9, abs_tol=1e-12):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió residual inconsistente.")

    constituents = payload.get("constituents")
    if not isinstance(constituents, list) or len(constituents) != len(attribution_keys):
        raise HTTPException(status_code=500, detail="Portfolio Attribution perdió constituyentes.")
    weight_sum = 0.0
    output_child_keys: list[str] = []
    for constituent in constituents:
        if not isinstance(constituent, dict):
            raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió constituyente inválido.")
        child_key = constituent.get("attributionKey")
        if not isinstance(child_key, str) or _SHA256_RE.fullmatch(child_key) is None:
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió attributionKey hija.")
        output_child_keys.append(child_key)
        weight_sum += _assert_finite(constituent.get("weight"), "constituent.weight")
        if not isinstance(constituent.get("weightEvidence"), dict):
            raise HTTPException(status_code=500, detail="Portfolio Attribution perdió provenance de peso.")
    if sorted(output_child_keys) != sorted(attribution_keys):
        raise HTTPException(status_code=500, detail="Portfolio Attribution alteró attributionKeys hijas.")
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió pesos inconsistentes.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Portfolio Attribution devolvió política inválida.")
    expected_policy = {
        "automaticTrading": False,
        "automaticProductionPromotion": False,
        "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
        "weighting": "historical_beginning_weights_diagnostic_only",
        "weightEvidence": "persisted_tamper_verified_reconciled_beginning_weights_required",
        "cashAttribution": "nonzero_beginning_cash_blocked_until_explicit_cash_attribution",
        "cashFlows": "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated",
        "observedReturn": "sealed_portfolio_twr_measurement_required",
        "valuationEvidence": "sealed_portfolio_twr_nlv_snapshots_required",
        "childAttributionEvidence": "persisted_tamper_verified_content_bound_attribution_keys_required",
    }
    for name, expected in expected_policy.items():
        if policy.get(name) != expected:
            raise HTTPException(status_code=500, detail=f"Portfolio Attribution perdió política {name}.")


@router.post("/portfolio-performance-attribution")
def post_portfolio_performance_attribution(
    request: PortfolioPerformanceAttributionRequest,
) -> dict[str, object]:
    """Reconcile a portfolio from sealed TWR, beginning weights and persisted child attributions."""

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

    twr_artifact = twr_record.get("artifact")
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
        raise HTTPException(status_code=500, detail="No se pudieron reverificar reconciliación/pesos históricos.") from exc

    canonical_weights, weight_binding = _canonical_weight_map(
        record=weight_record,
        weight_evidence_key=request.weightEvidenceKey,
        period_start=period_start,
    )

    attribution_keys: list[str] = []
    child_inputs: list[RecommendationPerformanceAttributionInput] = []
    seen_keys: set[str] = set()
    for requested in request.constituents:
        key = requested.attributionKey.lower()
        if _SHA256_RE.fullmatch(key) is None:
            raise HTTPException(status_code=400, detail="attributionKey hija inválida.")
        if key in seen_keys:
            raise HTTPException(status_code=400, detail="Portfolio Attribution recibió attributionKey hija duplicada.")
        seen_keys.add(key)
        try:
            record = _attribution_repository.get_by_key(attribution_key=key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        child = _persisted_child_input(
            record=record,
            benchmark_id=request.benchmarkId,
            reporting_currency=reporting_currency,
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        attribution_keys.append(key)
        child_inputs.append(child)

    requested_ids = [child.instrument_id for child in child_inputs]
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(status_code=400, detail="Portfolio Attribution recibió instrumento hijo duplicado.")
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
    constituents = tuple(
        PortfolioAttributionConstituent(
            weight=canonical_weights[child.instrument_id],
            attribution=child,
        )
        for child in child_inputs
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
                constituents=constituents,
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
    policy.update(
        {
            "cashFlows": "portfolio_return_uses_sealed_twr_constituent_cash_flow_attribution_not_estimated",
            "observedReturn": "sealed_portfolio_twr_measurement_required",
            "valuationEvidence": "sealed_portfolio_twr_nlv_snapshots_required",
            "weightEvidence": "persisted_tamper_verified_reconciled_beginning_weights_required",
            "cashAttribution": "nonzero_beginning_cash_blocked_until_explicit_cash_attribution",
            "childAttributionEvidence": "persisted_tamper_verified_content_bound_attribution_keys_required",
        }
    )
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
    payload["childAttributionEvidence"] = {
        "attributionKeys": attribution_keys,
        "tamperVerified": True,
        "callerSuppliedChildAttributionsAccepted": False,
        "identityBinding": "numeric_values_plus_pit_provenance_plus_period_and_instrument",
        "gate": "required_before_attribution",
    }
    payload["stateIntegrity"] = {
        "reconciliationKey": reconciliation_key,
        "portfolioStateKey": reconciliation_record["portfolio_state_key"],
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_attribution",
    }
    _assert_contract(payload, request.measurementKey, request.weightEvidenceKey, attribution_keys)
    return {"data": payload}
