from __future__ import annotations

import math
import re

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from app.api import recommendation_factor_risk as legacy_factor_risk
from app.api import recommendation_factor_risk_candidate_impact as legacy_candidate_impact
from app.repositories.recommendation_quality_factor_exposure_repository import (
    RecommendationQualityFactorExposureRepository,
)
from app.repositories.recommendation_value_factor_exposure_repository import (
    RecommendationValueFactorExposureRepository,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_value_repository = RecommendationValueFactorExposureRepository()
_quality_repository = RecommendationQualityFactorExposureRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SealedValueFactorRiskPositionRequest(legacy_factor_risk.FactorRiskPositionRequest):
    model_config = ConfigDict(extra="forbid")
    valueExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    qualityExposureKey: str | None = Field(default=None, min_length=64, max_length=64)


class SealedValueFactorRiskRequest(legacy_factor_risk.FactorRiskResearchRequest):
    model_config = ConfigDict(extra="forbid")
    positions: list[SealedValueFactorRiskPositionRequest] = Field(min_length=1, max_length=500)


class SealedCandidateBaselineRequest(legacy_candidate_impact.BaselineFactorExposureRequest):
    model_config = ConfigDict(extra="forbid")
    valueExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    qualityExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    factors: dict[str, float] = Field(default_factory=dict)


class SealedCandidateRequest(legacy_candidate_impact.CandidateFactorExposureRequest):
    model_config = ConfigDict(extra="forbid")
    valueExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    qualityExposureKey: str | None = Field(default=None, min_length=64, max_length=64)
    factors: dict[str, float] = Field(default_factory=dict)


class SealedCandidateImpactRequest(legacy_candidate_impact.FactorRiskCandidateImpactRequest):
    model_config = ConfigDict(extra="forbid")
    positions: list[SealedCandidateBaselineRequest] = Field(min_length=1, max_length=499)
    candidate: SealedCandidateRequest


def _load_factor(
    *,
    repository,
    key: str,
    instrument_id: int,
    as_of,
    factor: str,
    module: str,
) -> tuple[str, float]:
    try:
        record = repository.get(factor_exposure_key=key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=400, detail=f"No existe {factor} factor exposure persistido con esa identidad.")
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure persistido perdió artifact.")
    if artifact.get("module") != module:
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure persistido tiene módulo inválido.")
    if artifact.get("instrumentId") != instrument_id:
        raise HTTPException(status_code=400, detail=f"{factor}ExposureKey pertenece a otro instrumento.")
    artifact_as_of = legacy_factor_risk._artifact_datetime(artifact, "asOf")
    available_at = legacy_factor_risk._artifact_datetime(artifact, "availableAt")
    if artifact_as_of != as_of or available_at > as_of:
        raise HTTPException(status_code=400, detail=f"{factor}ExposureKey pertenece a otro asOf o viola PIT.")
    factors = artifact.get("factors")
    if not isinstance(factors, dict) or set(factors) != {factor}:
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure persistido es inválido.")
    raw = factors.get(factor)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure persistido no es finito.")
    value = float(raw)
    if value < -1.0 - 1e-12 or value > 1.0 + 1e-12:
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure persistido salió de [-1,1].")
    artifact_key = str(artifact.get("factorExposureKey") or "")
    if artifact_key != key.lower() or _SHA256_RE.fullmatch(artifact_key) is None:
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure perdió identidad SHA-256.")
    if artifact.get("advisoryStatus") != "no_advice" or artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail=f"{factor} factor exposure perdió contrato research-only.")
    return artifact_key, value


def _load_value(*, key: str, instrument_id: int, as_of) -> tuple[str, float]:
    return _load_factor(
        repository=_value_repository,
        key=key,
        instrument_id=instrument_id,
        as_of=as_of,
        factor="value",
        module="pit_value_factor_exposure",
    )


def _load_quality(*, key: str, instrument_id: int, as_of) -> tuple[str, float]:
    return _load_factor(
        repository=_quality_repository,
        key=key,
        instrument_id=instrument_id,
        as_of=as_of,
        factor="quality",
        module="pit_quality_factor_exposure",
    )


def _reject_free_fundamentals(factors: dict[str, float], field: str) -> None:
    names = {str(name).strip().lower() for name in factors}
    forbidden = sorted(names & {"value", "quality"})
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail=f"{field} no puede suministrar factores fundamentales {forbidden}; use exposure keys PIT selladas.",
        )


def _augment_fundamentals(
    *,
    item,
    as_of,
    factors: dict[str, float],
    source: str,
    source_ref: str,
) -> tuple[dict[str, float], str, str, dict[str, str], dict[str, float]]:
    keys: dict[str, str] = {}
    values: dict[str, float] = {}
    if item.valueExposureKey is not None:
        key, value = _load_value(key=item.valueExposureKey, instrument_id=item.instrumentId, as_of=as_of)
        factors["value"] = value
        keys["value"] = key
        values["value"] = value
        source += "+sealed_value_factor"
        source_ref += f";value:{key}"
    if item.qualityExposureKey is not None:
        key, value = _load_quality(key=item.qualityExposureKey, instrument_id=item.instrumentId, as_of=as_of)
        factors["quality"] = value
        keys["quality"] = key
        values["quality"] = value
        source += "+sealed_quality_factor"
        source_ref += f";quality:{key}"
    return factors, source, source_ref, keys, values


def _assert_position_fundamentals(
    *,
    output_positions: object,
    expected_by_id: dict[int, dict[str, float]],
) -> None:
    if not isinstance(output_positions, list):
        raise HTTPException(status_code=500, detail="Factor Risk sellado perdió positions.")
    seen: set[int] = set()
    for position in output_positions:
        if not isinstance(position, dict):
            raise HTTPException(status_code=500, detail="Factor Risk sellado devolvió posición inválida.")
        instrument_id = position.get("instrumentId")
        factors = position.get("factors")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or not isinstance(factors, dict):
            raise HTTPException(status_code=500, detail="Factor Risk sellado perdió identidad/factores.")
        if instrument_id in seen:
            raise HTTPException(status_code=500, detail="Factor Risk sellado duplicó instrumento.")
        seen.add(instrument_id)
        expected = expected_by_id.get(instrument_id, {})
        for factor in ("value", "quality"):
            if factor not in expected:
                if factor in factors:
                    raise HTTPException(status_code=500, detail=f"Factor Risk inventó {factor} sin evidencia sellada.")
                continue
            actual = factors.get(factor)
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(
                float(actual), expected[factor], rel_tol=0.0, abs_tol=1e-12
            ):
                raise HTTPException(status_code=500, detail=f"Factor Risk alteró {factor} sellado.")


@router.post("/factor-risk")
def post_factor_risk_with_sealed_value(
    request: SealedValueFactorRiskRequest,
) -> dict[str, object]:
    """Run reconciled Factor Risk with fundamental factors sealed upstream."""

    as_of = legacy_factor_risk._aware_utc(request.asOf, "asOf")
    factor_keys = {"value": {}, "quality": {}}
    expected_by_id: dict[int, dict[str, float]] = {}
    legacy_positions: list[legacy_factor_risk.FactorRiskPositionRequest] = []
    for index, item in enumerate(request.positions):
        _reject_free_fundamentals(item.factors, f"positions[{index}].factors")
        factors, source, source_ref, keys, values = _augment_fundamentals(
            item=item,
            as_of=as_of,
            factors=dict(item.factors),
            source=item.source,
            source_ref=item.sourceRef,
        )
        expected_by_id[item.instrumentId] = values
        for factor, key in keys.items():
            factor_keys[factor][str(item.instrumentId)] = key
        legacy_positions.append(
            legacy_factor_risk.FactorRiskPositionRequest(
                instrumentId=item.instrumentId,
                symbol=item.symbol,
                marketExposureKey=item.marketExposureKey,
                priceExposureKey=item.priceExposureKey,
                sizeExposureKey=item.sizeExposureKey,
                rateExposureKey=item.rateExposureKey,
                exposureAvailableAt=item.exposureAvailableAt,
                source=source,
                sourceRef=source_ref,
                factors=factors,
            )
        )

    response = legacy_factor_risk.post_factor_risk(
        legacy_factor_risk.FactorRiskResearchRequest(
            portfolioId=request.portfolioId,
            reportingCurrency=request.reportingCurrency,
            reconciliationKey=request.reconciliationKey,
            portfolioValuationEvidenceFingerprint=request.portfolioValuationEvidenceFingerprint,
            asOf=request.asOf,
            positions=legacy_positions,
        )
    )
    data = response.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Factor Risk sellado perdió payload.")
    state = data.get("stateIntegrity")
    if not isinstance(state, dict):
        raise HTTPException(status_code=500, detail="Factor Risk sellado perdió stateIntegrity.")
    _assert_position_fundamentals(output_positions=data.get("positions"), expected_by_id=expected_by_id)

    state["valueExposureKeys"] = factor_keys["value"]
    state["qualityExposureKeys"] = factor_keys["quality"]
    state["valueFactorDerivation"] = "sealed_issuer_deduplicated_pit_book_to_market_or_explicitly_missing"
    state["qualityFactorDerivation"] = "sealed_issuer_deduplicated_pit_annual_operating_margin_or_explicitly_missing"
    state["callerSuppliedValueAccepted"] = False
    state["callerSuppliedQualityAccepted"] = False
    state["callerSuppliedNumericFactorAccepted"] = False
    return {"data": data}


@router.post("/factor-risk/candidate-impact")
def post_candidate_impact_with_value_block(
    request: SealedCandidateImpactRequest,
) -> dict[str, object]:
    """Compare a hypothetical candidate using only sealed fundamental factor evidence."""

    as_of = legacy_candidate_impact._aware_utc(request.asOf, "asOf")
    baseline_keys = {"value": {}, "quality": {}}
    baseline_has = {"value": True, "quality": True}
    legacy_positions: list[legacy_candidate_impact.BaselineFactorExposureRequest] = []
    for index, item in enumerate(request.positions):
        _reject_free_fundamentals(item.factors, f"positions[{index}].factors")
        factors, source, source_ref, keys, _ = _augment_fundamentals(
            item=item,
            as_of=as_of,
            factors=dict(item.factors),
            source=item.source,
            source_ref=item.sourceRef,
        )
        for factor in ("value", "quality"):
            if factor not in keys:
                baseline_has[factor] = False
            else:
                baseline_keys[factor][str(item.instrumentId)] = keys[factor]
        legacy_positions.append(
            legacy_candidate_impact.BaselineFactorExposureRequest(
                instrumentId=item.instrumentId,
                symbol=item.symbol,
                exposureAvailableAt=item.exposureAvailableAt,
                source=source,
                sourceRef=source_ref,
                factors=factors,
            )
        )

    item = request.candidate
    _reject_free_fundamentals(item.factors, "candidate.factors")
    candidate_factors, candidate_source, candidate_ref, candidate_keys, candidate_values = _augment_fundamentals(
        item=item,
        as_of=as_of,
        factors=dict(item.factors),
        source=item.source,
        source_ref=item.sourceRef,
    )
    legacy_candidate = legacy_candidate_impact.CandidateFactorExposureRequest(
        instrumentId=item.instrumentId,
        symbol=item.symbol,
        weight=item.weight,
        exposureAvailableAt=item.exposureAvailableAt,
        source=candidate_source,
        sourceRef=candidate_ref,
        factors=candidate_factors,
    )
    response = legacy_candidate_impact.post_factor_risk_candidate_impact(
        legacy_candidate_impact.FactorRiskCandidateImpactRequest(
            portfolioId=request.portfolioId,
            reportingCurrency=request.reportingCurrency,
            reconciliationKey=request.reconciliationKey,
            portfolioValuationEvidenceFingerprint=request.portfolioValuationEvidenceFingerprint,
            asOf=request.asOf,
            positions=legacy_positions,
            candidate=legacy_candidate,
        )
    )
    data = response.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió payload.")
    candidate_output = data.get("candidate")
    if not isinstance(candidate_output, dict) or not isinstance(candidate_output.get("factors"), dict):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió factores del candidato.")
    output_factors = candidate_output["factors"]
    assert isinstance(output_factors, dict)
    for factor in ("value", "quality"):
        expected = candidate_values.get(factor)
        if expected is None:
            if factor in output_factors:
                raise HTTPException(status_code=500, detail=f"Candidate Impact inventó {factor} del candidato.")
        else:
            actual = output_factors.get(factor)
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-12):
                raise HTTPException(status_code=500, detail=f"Candidate Impact alteró {factor} sellado del candidato.")

    comparable = data.get("comparableFactors")
    if not isinstance(comparable, list):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió comparableFactors.")
    for factor in ("value", "quality"):
        should_compare = baseline_has[factor] and factor in candidate_keys
        if (factor in comparable) != should_compare:
            raise HTTPException(status_code=500, detail=f"Candidate Impact devolvió cobertura incoherente para {factor}.")

    state = data.get("stateIntegrity")
    if not isinstance(state, dict):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió stateIntegrity.")
    state["baselineValueExposureKeys"] = baseline_keys["value"]
    state["baselineQualityExposureKeys"] = baseline_keys["quality"]
    state["candidateValueExposureKey"] = candidate_keys.get("value")
    state["candidateQualityExposureKey"] = candidate_keys.get("quality")
    state["callerSuppliedValueAccepted"] = False
    state["callerSuppliedQualityAccepted"] = False
    state["callerSuppliedNumericFactorAccepted"] = False
    state["fundamentalFactorComparison"] = "only_when_baseline_and_candidate_have_matching_sealed_pit_evidence"
    return {"data": data}
