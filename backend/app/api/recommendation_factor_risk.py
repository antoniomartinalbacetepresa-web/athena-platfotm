from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_factor_exposure_repository import RecommendationFactorExposureRepository
from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.repositories.recommendation_price_factor_exposure_repository import (
    RecommendationPriceFactorExposureRepository,
)
from app.repositories.recommendation_size_factor_exposure_repository import (
    RecommendationSizeFactorExposureRepository,
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
_factor_exposure_repository = RecommendationFactorExposureRepository()
_price_factor_repository = RecommendationPriceFactorExposureRepository()
_size_factor_repository = RecommendationSizeFactorExposureRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SEALED_CALLER_FORBIDDEN = {"market", "momentum", "low_volatility", "size", "usd_fx"}


class FactorRiskPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    marketExposureKey: str = Field(min_length=64, max_length=64)
    priceExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    sizeExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(default_factory=dict)


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
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _require_hash_map(value: object, field: str, *, allow_empty: bool) -> dict[str, str]:
    if not isinstance(value, dict) or (not value and not allow_empty):
        raise HTTPException(status_code=500, detail=f"Factor Risk perdió {field} válido.")
    result: dict[str, str] = {}
    for instrument_id, key in value.items():
        if not str(instrument_id).isdigit() or not isinstance(key, str) or _SHA256_RE.fullmatch(key) is None:
            raise HTTPException(status_code=500, detail=f"Factor Risk devolvió {field} inválido.")
        result[str(instrument_id)] = key
    return result


def _artifact_datetime(artifact: dict[str, object], field: str) -> datetime:
    return _datetime_value(artifact.get(field), field)


def _datetime_value(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Factor evidence perdió {field} válido.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=500, detail=f"Factor evidence perdió timezone en {field}.")
    return parsed.astimezone(timezone.utc)


def _currency(value: object, field: str) -> str:
    result = str(value or "").strip().upper()
    if len(result) != 3 or not result.isalpha():
        raise HTTPException(status_code=500, detail=f"Factor Risk perdió {field} ISO válido.")
    return result


def _valuation_positions(record: dict[str, object], *, as_of: datetime) -> dict[int, dict[str, object]]:
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Valoración PIT persistida perdió artifact.")
    positions = artifact.get("positions")
    if not isinstance(positions, list):
        raise HTTPException(status_code=500, detail="Valoración PIT persistida perdió positions.")
    result: dict[int, dict[str, object]] = {}
    for position in positions:
        if not isinstance(position, dict):
            raise HTTPException(status_code=500, detail="Valoración PIT contiene posición inválida.")
        instrument_id = position.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise HTTPException(status_code=500, detail="Valoración PIT perdió instrumentId.")
        if instrument_id in result:
            raise HTTPException(status_code=500, detail="Valoración PIT duplicó instrumentId.")
        fx = position.get("fx")
        if not isinstance(fx, dict) or fx.get("historicalPointInTimeEligible") is not True:
            raise HTTPException(status_code=500, detail="Valoración PIT perdió evidencia FX verificable.")
        rate = fx.get("rate")
        if not _finite_number(rate) or float(rate) <= 0.0:
            raise HTTPException(status_code=500, detail="Valoración PIT contiene FX no finito/positivo.")
        observed = _datetime_value(fx.get("observedAt"), "fx.observedAt")
        retrieved = _datetime_value(fx.get("retrievedAt"), "fx.retrievedAt")
        if observed > retrieved or retrieved > as_of:
            raise HTTPException(status_code=500, detail="Valoración PIT contiene FX con lookahead.")
        result[instrument_id] = position
    return result


def _usd_fx_translation_exposure(position: dict[str, object], reporting_currency: str) -> float | None:
    instrument_currency = _currency(position.get("instrumentCurrency"), "instrumentCurrency")
    reporting = _currency(reporting_currency, "reportingCurrency")
    if instrument_currency == reporting:
        return 0.0
    if instrument_currency == "USD":
        return 1.0
    if reporting == "USD":
        return -1.0
    return None


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
    _require_hash_map(state_integrity.get("marketExposureKeys"), "marketExposureKeys", allow_empty=False)
    _require_hash_map(state_integrity.get("priceExposureKeys"), "priceExposureKeys", allow_empty=True)
    _require_hash_map(state_integrity.get("sizeExposureKeys"), "sizeExposureKeys", allow_empty=True)
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Factor Risk aceptó estado no reconciliado/verificado.")
    if state_integrity.get("gate") != "required_before_factor_risk":
        raise HTTPException(status_code=500, detail="Factor Risk perdió la puerta obligatoria de integridad.")
    expected_contract = {
        "weightDerivation": "derived_from_reconciled_state_and_sealed_pit_valuation",
        "marketFactorDerivation": "sealed_pit_market_observations_only",
        "priceFactorDerivation": "sealed_pit_market_observations_or_explicitly_missing",
        "sizeFactorDerivation": "sealed_cross_sectional_pit_market_cap_or_explicitly_missing",
        "usdFxFactorDerivation": "sealed_portfolio_valuation_translation_exposure_or_explicitly_missing",
        "callerSuppliedMarketAccepted": False,
        "callerSuppliedPriceFactorsAccepted": False,
        "callerSuppliedSizeAccepted": False,
        "callerSuppliedUsdFxAccepted": False,
        "callerSuppliedWeightAccepted": False,
    }
    for field, expected in expected_contract.items():
        if state_integrity.get(field) != expected:
            raise HTTPException(status_code=500, detail=f"Factor Risk perdió contrato de integridad {field}.")
    if not _finite_number(state_integrity.get("cashWeight")):
        raise HTTPException(status_code=500, detail="Factor Risk perdió cashWeight derivado.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió una política inválida.")
    if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk intentó habilitar automatización.")
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
    for value in (invested, cash, payload.get("grossFactorExposure"), payload.get("maxAbsoluteFactorExposure")):
        if not _finite_number(value):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió métricas no finitas.")
    if abs(float(invested) + float(cash) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk devolvió pesos de cartera incoherentes.")
    if not math.isclose(float(cash), float(state_integrity["cashWeight"]), rel_tol=0.0, abs_tol=1e-9):
        raise HTTPException(status_code=500, detail="Factor Risk no reconcilió cashWeight con evidencia derivada.")

    exposures = payload.get("weightedExposures")
    coverage = payload.get("factorCoverageWeights")
    fully_covered = payload.get("fullyCoveredFactors")
    if not isinstance(exposures, dict) or not isinstance(coverage, dict) or set(exposures) != set(coverage):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió exposiciones/cobertura inválidas.")
    for name, value in exposures.items():
        if not isinstance(name, str) or not _finite_number(value) or not _finite_number(coverage.get(name)):
            raise HTTPException(status_code=500, detail="Factor Risk devolvió exposición/cobertura no finita.")
        if float(coverage[name]) < -1e-12 or float(coverage[name]) > float(invested) + 1e-9:
            raise HTTPException(status_code=500, detail="Factor Risk devolvió cobertura fuera de rango.")
    if not isinstance(fully_covered, list):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió fullyCoveredFactors inválido.")
    expected_fully = {name for name, value in coverage.items() if float(invested) > 0.0 and abs(float(value) - float(invested)) <= 1e-9}
    if set(fully_covered) != expected_fully:
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
        factors = position.get("factors")
        if (
            isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0
            or not isinstance(symbol, str) or not symbol.strip()
            or not isinstance(position.get("source"), str) or not str(position.get("source")).strip()
            or not isinstance(position.get("sourceRef"), str) or not str(position.get("sourceRef")).strip()
            or not isinstance(position.get("exposureAvailableAt"), str) or not str(position.get("exposureAvailableAt")).strip()
            or not isinstance(factors, dict) or "market" not in factors or not _finite_number(position.get("weight"))
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
    if dominant is not None and (not isinstance(dominant, str) or dominant not in set(fully_covered)):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió dominantFactor sin cobertura completa.")


@router.post("/factor-risk")
def post_factor_risk(request: FactorRiskResearchRequest) -> dict[str, object]:
    """Measure PIT factor exposure with reconciled weights and sealed factor evidence."""

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
        weight_evidence = _weight_service.build(reconciliation_record=reconciliation_record, valuation_record=valuation_record)
        _weight_service.validate_artifact(weight_evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo verificar/derivar la evidencia de pesos para Factor Risk.") from exc

    if weight_evidence["portfolioId"] != request.portfolioId.strip():
        raise HTTPException(status_code=400, detail="Weight evidence pertenece a otra cartera.")
    if weight_evidence["reportingCurrency"] != request.reportingCurrency.strip().upper():
        raise HTTPException(status_code=400, detail="Weight evidence usa otra moneda de reporting.")
    if _datetime_value(weight_evidence["asOf"], "weightEvidence.asOf") != as_of:
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
    valuation_by_id = _valuation_positions(valuation_record, as_of=as_of)
    if set(valuation_by_id) != set(weights_by_id):
        raise HTTPException(status_code=500, detail="Valoración y weight evidence perdieron identidad común.")

    request_ids = [item.instrumentId for item in request.positions]
    if len(request_ids) != len(set(request_ids)):
        raise HTTPException(status_code=400, detail="Factor Risk request contiene instrumentId duplicado.")
    if set(request_ids) != set(weights_by_id):
        missing = sorted(set(weights_by_id) - set(request_ids))
        extra = sorted(set(request_ids) - set(weights_by_id))
        raise HTTPException(status_code=400, detail=f"Factor exposure identity mismatch; missing={missing}, extra={extra}.")

    positions: list[FactorRiskPositionInput] = []
    market_keys: dict[str, str] = {}
    price_keys: dict[str, str] = {}
    size_keys: dict[str, str] = {}
    for item in request.positions:
        derived = weights_by_id[item.instrumentId]
        valued = valuation_by_id[item.instrumentId]
        derived_symbol = str(derived.get("symbol") or "").strip().upper()
        if item.symbol.strip().upper() != derived_symbol:
            raise HTTPException(status_code=400, detail=f"Símbolo de instrumentId={item.instrumentId} no coincide con la valoración canónica.")
        normalized_caller_factors = {str(name).strip().lower() for name in item.factors}
        forbidden = sorted(normalized_caller_factors & _SEALED_CALLER_FORBIDDEN)
        if forbidden:
            raise HTTPException(status_code=400, detail=f"El caller no puede suministrar factores sellados {forbidden}; use evidencia PIT sellada.")
        weight = derived.get("weight")
        if not _finite_number(weight):
            raise HTTPException(status_code=500, detail="Weight evidence devolvió weight no finito.")

        try:
            factor_record = _factor_exposure_repository.get(factor_exposure_key=item.marketExposureKey)
            if factor_record is None:
                raise ValueError("No existe market factor exposure persistido con esa identidad.")
            market_artifact = factor_record.get("artifact")
            if not isinstance(market_artifact, dict):
                raise ValueError("Market factor exposure persistido perdió artifact.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if market_artifact.get("instrumentId") != item.instrumentId or _artifact_datetime(market_artifact, "asOf") != as_of:
            raise HTTPException(status_code=400, detail="marketExposureKey pertenece a otro instrumento/asOf.")
        market_factors = market_artifact.get("factors")
        if not isinstance(market_factors, dict) or set(market_factors) != {"market"} or not _finite_number(market_factors.get("market")):
            raise HTTPException(status_code=500, detail="Market factor exposure persistido es inválido.")
        market_key = str(market_artifact.get("factorExposureKey") or "")
        if _SHA256_RE.fullmatch(market_key) is None:
            raise HTTPException(status_code=500, detail="Market factor exposure perdió identidad SHA-256.")
        market_keys[str(item.instrumentId)] = market_key
        evidence_times = [_artifact_datetime(market_artifact, "availableAt")]
        combined_factors = dict(item.factors)
        combined_factors["market"] = float(market_factors["market"])
        refs = [f"market:{market_key}"]
        sources = ["sealed_market_beta"]

        if item.priceExposureKey is not None:
            try:
                price_record = _price_factor_repository.get(factor_exposure_key=item.priceExposureKey)
                if price_record is None:
                    raise ValueError("No existe price factor exposure persistido con esa identidad.")
                price_artifact = price_record.get("artifact")
                if not isinstance(price_artifact, dict):
                    raise ValueError("Price factor exposure persistido perdió artifact.")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if price_artifact.get("instrumentId") != item.instrumentId or _artifact_datetime(price_artifact, "asOf") != as_of:
                raise HTTPException(status_code=400, detail="priceExposureKey pertenece a otro instrumento/asOf.")
            price_factors = price_artifact.get("factors")
            if not isinstance(price_factors, dict) or set(price_factors) != {"momentum", "low_volatility"} or any(not _finite_number(value) for value in price_factors.values()):
                raise HTTPException(status_code=500, detail="Price factor exposure persistido es inválido.")
            price_key = str(price_artifact.get("factorExposureKey") or "")
            if _SHA256_RE.fullmatch(price_key) is None:
                raise HTTPException(status_code=500, detail="Price factor exposure perdió identidad SHA-256.")
            price_keys[str(item.instrumentId)] = price_key
            evidence_times.append(_artifact_datetime(price_artifact, "availableAt"))
            combined_factors["momentum"] = float(price_factors["momentum"])
            combined_factors["low_volatility"] = float(price_factors["low_volatility"])
            refs.append(f"price:{price_key}")
            sources.append("sealed_price_factors")

        if item.sizeExposureKey is not None:
            try:
                size_record = _size_factor_repository.get(factor_exposure_key=item.sizeExposureKey)
                if size_record is None:
                    raise ValueError("No existe size factor exposure persistido con esa identidad.")
                size_artifact = size_record.get("artifact")
                if not isinstance(size_artifact, dict):
                    raise ValueError("Size factor exposure persistido perdió artifact.")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if size_artifact.get("instrumentId") != item.instrumentId or _artifact_datetime(size_artifact, "asOf") != as_of:
                raise HTTPException(status_code=400, detail="sizeExposureKey pertenece a otro instrumento/asOf.")
            size_factors = size_artifact.get("factors")
            if not isinstance(size_factors, dict) or set(size_factors) != {"size"} or not _finite_number(size_factors.get("size")):
                raise HTTPException(status_code=500, detail="Size factor exposure persistido es inválido.")
            size_value = float(size_factors["size"])
            if size_value < -1.0 - 1e-12 or size_value > 1.0 + 1e-12:
                raise HTTPException(status_code=500, detail="Size factor exposure salió de [-1,1].")
            size_key = str(size_artifact.get("factorExposureKey") or "")
            if _SHA256_RE.fullmatch(size_key) is None:
                raise HTTPException(status_code=500, detail="Size factor exposure perdió identidad SHA-256.")
            size_keys[str(item.instrumentId)] = size_key
            evidence_times.append(_artifact_datetime(size_artifact, "availableAt"))
            combined_factors["size"] = size_value
            refs.append(f"size:{size_key}")
            sources.append("sealed_size_factor")

        usd_fx = _usd_fx_translation_exposure(valued, request.reportingCurrency)
        if usd_fx is not None:
            combined_factors["usd_fx"] = usd_fx
            fx = valued.get("fx")
            assert isinstance(fx, dict)
            evidence_times.append(_datetime_value(fx.get("retrievedAt"), "fx.retrievedAt"))
            refs.append(f"usd_fx:valuation:{request.portfolioValuationEvidenceFingerprint}")
            sources.append("sealed_portfolio_valuation_fx")

        caller_available = _aware_utc(item.exposureAvailableAt, "positions.exposureAvailableAt")
        evidence_times.append(caller_available)
        refs.append(f"caller:{item.sourceRef.strip()}")
        sources.append(item.source.strip())
        positions.append(
            FactorRiskPositionInput(
                instrument_id=item.instrumentId,
                symbol=derived_symbol,
                weight=float(weight),
                exposure_available_at=max(evidence_times),
                source="+".join(sources),
                source_ref=";".join(refs),
                factors=combined_factors,
            )
        )

    try:
        result = factor_risk_service.evaluate(as_of=as_of, positions=tuple(positions))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="No se pudo evaluar Factor Risk PIT de ATHENA.") from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk devolvió un contrato inválido.")
    payload["portfolioId"] = request.portfolioId.strip()
    payload["reportingCurrency"] = request.reportingCurrency.strip().upper()
    payload["stateIntegrity"] = {
        "reconciliationKey": str(weight_evidence["reconciliationKey"]),
        "portfolioStateKey": str(weight_evidence["portfolioStateKey"]),
        "portfolioValuationEvidenceFingerprint": str(weight_evidence["portfolioValuationEvidenceFingerprint"]),
        "weightEvidenceKey": str(weight_evidence["weightEvidenceKey"]),
        "marketExposureKeys": market_keys,
        "priceExposureKeys": price_keys,
        "sizeExposureKeys": size_keys,
        "reconciled": True,
        "tamperVerified": True,
        "gate": "required_before_factor_risk",
        "weightDerivation": "derived_from_reconciled_state_and_sealed_pit_valuation",
        "marketFactorDerivation": "sealed_pit_market_observations_only",
        "priceFactorDerivation": "sealed_pit_market_observations_or_explicitly_missing",
        "sizeFactorDerivation": "sealed_cross_sectional_pit_market_cap_or_explicitly_missing",
        "usdFxFactorDerivation": "sealed_portfolio_valuation_translation_exposure_or_explicitly_missing",
        "callerSuppliedMarketAccepted": False,
        "callerSuppliedPriceFactorsAccepted": False,
        "callerSuppliedSizeAccepted": False,
        "callerSuppliedUsdFxAccepted": False,
        "callerSuppliedWeightAccepted": False,
        "cashWeight": weight_evidence["cashWeight"],
    }
    _assert_contract(payload)
    return {"data": payload}
