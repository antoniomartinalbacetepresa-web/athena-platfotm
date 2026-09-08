from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.recommendation_factor_risk_service import (
    FactorRiskPositionInput,
    RecommendationFactorRiskService,
)
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

factor_risk_service = RecommendationFactorRiskService()
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_valuation_repository = RecommendationPortfolioValuationEvidenceRepository()
_weight_service = RecommendationReconciledPortfolioWeightService()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FactorRiskPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class FactorRiskResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    reconciliationKey: str = Field(min_length=64, max_length=64)
    portfolioValuationEvidenceFingerprint: str = Field(min_length=64, max_length=64)
    asOf: datetime
    positions: list[FactorRiskPositionRequest] = Field(min_length=1, max_length=500)


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(status_code=400, detail=f"{field} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Factor Risk violó el contrato no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar ponderación.")
    if not isinstance(payload.get("portfolioId"), str) or not str(payload.get("portfolioId")).strip():
        raise HTTPException(status_code=500, detail="Factor Risk perdió identidad de cartera.")
    reporting_currency = payload.get("reportingCurrency")
    if not isinstance(reporting_currency, str) or len(reporting_currency) != 3 or not reporting_currency.isalpha():
        raise HTTPException(status_code=500, detail="Factor Risk perdió moneda de reporting.")
    state_integrity = payload.get("stateIntegrity")
    if not isinstance(state_integrity, dict):
        raise HTTPException(status_code=500, detail="Factor Risk perdió gating de reconciliación.")
    for field in ("reconciliationKey", "portfolioStateKey", "weightEvidenceKey", "portfolioValuationEvidenceFingerprint"):
        value = state_integrity.get(field)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            raise HTTPException(status_code=500, detail=f"Factor Risk perdió {field} válido.")
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Factor Risk aceptó estado no reconciliado/verificado.")
    if state_integrity.get("gate") != "required_before_factor_risk":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la puerta obligatoria de integridad.")
    if state_integrity.get("weightDerivation") != "derived_from_reconciled_state_and_sealed_pit_valuation":
        raise HTTPException(status_code=500, detail="Factor Risk no derivó pesos desde evidencia reconciliada/PIT.")
    if state_integrity.get("callerSuppliedWeightAccepted") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk aceptó pesos arbitrarios del caller.")
    if not _finite_number(state_integrity.get("cashWeight")):
        raise HTTPException(status_code=500, detail="Factor Risk perdió cashWeight derivado.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió una política inválida.")
    if policy.get("automaticTrading") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar trading automático.")
    if policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó promover producción automáticamente.")
    if policy.get("identity") != "duplicate_instrument_or_symbol_forbidden":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía de identidad.")
    if policy.get("fx") != "usd_fx_is_explicit_factor_not_silently_netting_currency_risk":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía explícita de FX.")
    if policy.get("missingFactorCoverage") != "reported_explicitly_never_imputed_as_zero":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la garantía contra imputación silenciosa.")
    if policy.get("thresholds") != "not_calibrated":
        raise HTTPException(status_code=500, detail="Factor Risk intentó usar umbrales no calibrados.")

    count = payload.get("positionCount")
    invested = payload.get("investedWeight")
    cash = payload.get("cashWeight")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió positionCount inválido.")
    for value in (
        invested,
        cash,
        payload.get("grossFactorExposure"),
        payload.get("maxAbsoluteFactorExposure"),
    ):
        if not _finite_number(value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió métricas no finitas.")
    if abs(float(invested) + float(cash) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió pesos de cartera incoherentes.")
    if not math.isclose(float(cash), float(state_integrity["cashWeight"]), rel_tol=0.0, abs_tol=1e-9):
        raise HTTPException(status_code=500, detail="Factor Risk no reconcilió cashWeight con la evidencia derivada.")

    exposures = payload.get("weightedExposures")
    coverage = payload.get("factorCoverageWeights")
    fully_covered = payload.get("fullyCoveredFactors")
    if not isinstance(exposures, dict) or not isinstance(coverage, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió exposiciones/cobertura inválidas.")
    if set(exposures) != set(coverage):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura factorial incompleta.")
    for name, value in exposures.items():
        if not isinstance(name, str) or not _finite_number(value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió exposición no finita.")
        coverage_value = coverage.get(name)
        if not _finite_number(coverage_value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura no finita.")
        if float(coverage_value) < -1e-12 or float(coverage_value) > float(invested) + 1e-9:
            raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura fuera de rango.")
    if not isinstance(fully_covered, list) or any(
        not isinstance(name, str) or name not in exposures for name in fully_covered
    ):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió fullyCoveredFactors inválido.")
    expected_fully_covered = {
        name
        for name, value in coverage.items()
        if float(invested) > 0.0 and abs(float(value) - float(invested)) <= 1e-9
    }
    if set(fully_covered) != expected_fully_covered:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura completa incoherente.")

    positions = payload.get("positions")
    if not isinstance(positions, list) or len(positions) != count:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia de posiciones inválida.")
    seen_ids: set[int] = set()
    seen_symbols: set[str] = set()
    for position in positions:
        if not isinstance(position, dict):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia PIT inválida.")
        instrument_id = position.get("instrumentId")
        symbol = position.get("symbol")
        source = position.get("source")
        source_ref = position.get("sourceRef")
        available_at = position.get("exposureAvailableAt")
        factors = position.get("factors")
        weight = position.get("weight")
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or instrument_id <= 0
            or not isinstance(symbol, str)
            or not symbol.strip()
            or not isinstance(source, str)
            or not source.strip()
            or not isinstance(source_ref, str)
            or not source_ref.strip()
            or not isinstance(available_at, str)
            or not available_at.strip()
            or not isinstance(factors, dict)
            or not factors
            or not _finite_number(weight)
        ):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió provenance PIT incompleta.")
        normalized_symbol = symbol.strip().upper()
        if instrument_id in seen_ids or normalized_symbol in seen_symbols:
            raise HTTPException(status_code=500, detail="Factor Risk devolvió identidad duplicada.")
        seen_ids.add(instrument_id)
        seen_symbols.add(normalized_symbol)
        for factor, value in factors.items():
            if not isinstance(factor, str) or factor not in exposures or not _finite_number(value):
                raise HTTPException(status_code=500, detail="Factor Risk devolvió evidencia factorial inválida.")

    dominant = payload.get("dominantFactor")
    if dominant is not None and (
        not isinstance(dominant, str) or dominant not in set(fully_covered)
    ):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió dominantFactor sin cobertura completa.")


@router.post("/factor-risk")
def post_factor_risk(request: FactorRiskResearchRequest) -> dict[str, object]:
    """Measure PIT factor exposure using only weights derived from reconciled portfolio evidence."""

    as_of = _aware_utc(request.asOf, "asOf")
    try:
        reconciliation_record = _reconciliation_repository.require_reconciled(
            reconciliation_key=request.reconciliationKey,
            portfolio_id=request.portfolioId,
            reporting_currency=request.reportingCurrency,
            as_of=as_of,
        )
        valuation_record = _valuation_repository.get(
            valuation_fingerprint=request.portfolioValuationEvidenceFingerprint,
        )
        if valuation_record is None:
            raise ValueError("No existe valoración PIT sellada con ese fingerprint.")
        _valuation_repository.validate_record(valuation_record)
        weight_evidence = _weight_service.build(
            reconciliation_record=reconciliation_record,
            valuation_record=valuation_record,
        )
        _weight_service.validate_artifact(weight_evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo verificar/derivar la evidencia de pesos para Factor Risk.",
        ) from exc

    if weight_evidence["portfolioId"] != request.portfolioId.strip():
        raise HTTPException(status_code=400, detail="Weight evidence pertenece a otra cartera.")
    if weight_evidence["reportingCurrency"] != request.reportingCurrency.strip().upper():
        raise HTTPException(status_code=400, detail="Weight evidence usa otra moneda de reporting.")
    if datetime.fromisoformat(str(weight_evidence["asOf"]).replace("Z", "+00:00")) != as_of:
        raise HTTPException(status_code=400, detail="Weight evidence pertenece a otro asOf.")

    derived_positions = weight_evidence.get("positions")
    if not isinstance(derived_positions, list):
        raise HTTPException(status_code=500, detail="Weight evidence perdió positions.")
    weights_by_id: dict[int, dict[str, object]] = {}
    for item in derived_positions:
        if not isinstance(item, dict):
            raise HTTPException(status_code=500, detail="Weight evidence contiene posición inválida.")
        instrument_id = item.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise HTTPException(status_code=500, detail="Weight evidence perdió instrumentId canónico.")
        if instrument_id in weights_by_id:
            raise HTTPException(status_code=500, detail="Weight evidence duplicó instrumentId.")
        weights_by_id[instrument_id] = item

    request_ids = [item.instrumentId for item in request.positions]
    if len(request_ids) != len(set(request_ids)):
        raise HTTPException(status_code=400, detail="Factor Risk request contiene instrumentId duplicado.")
    if set(request_ids) != set(weights_by_id):
        missing = sorted(set(weights_by_id) - set(request_ids))
        extra = sorted(set(request_ids) - set(weights_by_id))
        raise HTTPException(
            status_code=400,
            detail=f"Factor exposure identity mismatch; missing={missing}, extra={extra}.",
        )

    positions: list[FactorRiskPositionInput] = []
    for item in request.positions:
        derived = weights_by_id[item.instrumentId]
        derived_symbol = str(derived.get("symbol") or "").strip().upper()
        if item.symbol.strip().upper() != derived_symbol:
            raise HTTPException(
                status_code=400,
                detail=f"Símbolo de instrumentId={item.instrumentId} no coincide con la valoración canónica.",
            )
        weight = derived.get("weight")
        if not _finite_number(weight):
            raise HTTPException(status_code=500, detail="Weight evidence devolvió weight no finito.")
        positions.append(
            FactorRiskPositionInput(
                instrument_id=item.instrumentId,
                symbol=derived_symbol,
                weight=float(weight),
                exposure_available_at=_aware_utc(
                    item.exposureAvailableAt,
                    "positions.exposureAvailableAt",
                ),
                source=item.source,
                source_ref=item.sourceRef,
                factors=dict(item.factors),
            )
        )

    try:
        result = factor_risk_service.evaluate(
            as_of=as_of,
            positions=tuple(positions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar Factor Risk PIT de ATHENA.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió un contrato inválido.")
    payload["portfolioId"] = request.portfolioId.strip()
    payload["reportingCurrency"] = request.reportingCurrency.strip().upper()
    payload["stateIntegrity"] = {
        "reconciliationKey": str(weight_evidence["reconciliationKey"]),
        "portfolioStateKey": str(weight_evidence["portfolioStateKey"]),
        "portfolioValuationEvidenceFingerprint": str(
            weight_evidence["portfolioValuationEvidenceFingerprint"]
        ),
        "weightEvidenceKey": str(weight_evidence["weightEvidenceKey"]),
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_factor_risk",
        "weightDerivation": "derived_from_reconciled_state_and_sealed_pit_valuation",
        "callerSuppliedWeightAccepted": False,
        "cashWeight": weight_evidence["cashWeight"],
    }
    _assert_contract(payload)
    return {"data": payload}
