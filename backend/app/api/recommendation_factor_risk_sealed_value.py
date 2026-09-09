from __future__ import annotations

import math
import re
from datetime import timezone

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict, Field

from app.api import recommendation_factor_risk as legacy_factor_risk
from app.api import recommendation_factor_risk_candidate_impact as legacy_candidate_impact
from app.repositories.recommendation_value_factor_exposure_repository import (
    RecommendationValueFactorExposureRepository,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)
_value_repository = RecommendationValueFactorExposureRepository()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SealedValueFactorRiskPositionRequest(legacy_factor_risk.FactorRiskPositionRequest):
    model_config = ConfigDict(extra="forbid")
    valueExposureKey: str | None = Field(default=None, min_length=64, max_length=64)


class SealedValueFactorRiskRequest(legacy_factor_risk.FactorRiskResearchRequest):
    model_config = ConfigDict(extra="forbid")
    positions: list[SealedValueFactorRiskPositionRequest] = Field(min_length=1, max_length=500)


def _load_value(*, key: str, instrument_id: int, as_of) -> tuple[str, float]:
    try:
        record = _value_repository.get(factor_exposure_key=key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=400, detail="No existe value factor exposure persistido con esa identidad.")
    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        raise HTTPException(status_code=500, detail="Value factor exposure persistido perdió artifact.")
    if artifact.get("instrumentId") != instrument_id:
        raise HTTPException(status_code=400, detail="valueExposureKey pertenece a otro instrumento.")
    try:
        artifact_as_of = legacy_factor_risk._artifact_datetime(artifact, "asOf")
        available_at = legacy_factor_risk._artifact_datetime(artifact, "availableAt")
    except HTTPException:
        raise
    if artifact_as_of != as_of or available_at > as_of:
        raise HTTPException(status_code=400, detail="valueExposureKey pertenece a otro asOf o viola PIT.")
    factors = artifact.get("factors")
    if not isinstance(factors, dict) or set(factors) != {"value"}:
        raise HTTPException(status_code=500, detail="Value factor exposure persistido es inválido.")
    raw = factors.get("value")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise HTTPException(status_code=500, detail="Value factor exposure persistido no es finito.")
    value = float(raw)
    if value < -1.0 - 1e-12 or value > 1.0 + 1e-12:
        raise HTTPException(status_code=500, detail="Value factor exposure persistido salió de [-1,1].")
    artifact_key = str(artifact.get("factorExposureKey") or "")
    if artifact_key != key.lower() or _SHA256_RE.fullmatch(artifact_key) is None:
        raise HTTPException(status_code=500, detail="Value factor exposure perdió identidad SHA-256.")
    return artifact_key, value


def _reject_free_value(factors: dict[str, float], field: str) -> None:
    if "value" in {str(name).strip().lower() for name in factors}:
        raise HTTPException(
            status_code=400,
            detail=f"{field} no puede suministrar value; use valueExposureKey PIT sellado.",
        )


@router.post("/factor-risk")
def post_factor_risk_with_sealed_value(
    request: SealedValueFactorRiskRequest,
) -> dict[str, object]:
    """Run the existing reconciled Factor Risk boundary with value sealed upstream."""

    as_of = legacy_factor_risk._aware_utc(request.asOf, "asOf")
    value_keys: dict[str, str] = {}
    value_values: dict[int, float] = {}
    legacy_positions: list[legacy_factor_risk.FactorRiskPositionRequest] = []
    for index, item in enumerate(request.positions):
        _reject_free_value(item.factors, f"positions[{index}].factors")
        factors = dict(item.factors)
        source = item.source
        source_ref = item.sourceRef
        if item.valueExposureKey is not None:
            key, value = _load_value(
                key=item.valueExposureKey,
                instrument_id=item.instrumentId,
                as_of=as_of,
            )
            factors["value"] = value
            value_keys[str(item.instrumentId)] = key
            value_values[item.instrumentId] = value
            source = f"{source}+sealed_value_factor"
            source_ref = f"{source_ref};value:{key}"
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

    legacy_request = legacy_factor_risk.FactorRiskResearchRequest(
        portfolioId=request.portfolioId,
        reportingCurrency=request.reportingCurrency,
        reconciliationKey=request.reconciliationKey,
        portfolioValuationEvidenceFingerprint=request.portfolioValuationEvidenceFingerprint,
        asOf=request.asOf,
        positions=legacy_positions,
    )
    response = legacy_factor_risk.post_factor_risk(legacy_request)
    data = response.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Factor Risk sellado perdió payload.")
    state = data.get("stateIntegrity")
    if not isinstance(state, dict):
        raise HTTPException(status_code=500, detail="Factor Risk sellado perdió stateIntegrity.")

    output_positions = data.get("positions")
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
        expected = value_values.get(instrument_id)
        if expected is None:
            if "value" in factors:
                raise HTTPException(status_code=500, detail="Factor Risk inventó value sin evidencia sellada.")
        else:
            actual = factors.get("value")
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(
                float(actual), expected, rel_tol=0.0, abs_tol=1e-12
            ):
                raise HTTPException(status_code=500, detail="Factor Risk alteró value sellado.")

    state["valueExposureKeys"] = value_keys
    state["valueFactorDerivation"] = "sealed_issuer_deduplicated_pit_book_to_market_or_explicitly_missing"
    state["callerSuppliedValueAccepted"] = False
    if state.get("callerSuppliedValueAccepted") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk aceptó value libre.")
    return {"data": data}


@router.post("/factor-risk/candidate-impact")
def post_candidate_impact_with_value_block(
    request: legacy_candidate_impact.FactorRiskCandidateImpactRequest,
) -> dict[str, object]:
    """Keep hypothetical candidate impact closed to value until candidate PIT evidence exists."""

    for index, item in enumerate(request.positions):
        _reject_free_value(item.factors, f"positions[{index}].factors")
    _reject_free_value(request.candidate.factors, "candidate.factors")
    response = legacy_candidate_impact.post_factor_risk_candidate_impact(request)
    data = response.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió payload.")
    comparable = data.get("comparableFactors")
    candidate = data.get("candidate")
    if isinstance(comparable, list) and "value" in comparable:
        raise HTTPException(status_code=500, detail="Candidate Impact comparó value sin evidencia sellada del candidato.")
    if isinstance(candidate, dict):
        factors = candidate.get("factors")
        if isinstance(factors, dict) and "value" in factors:
            raise HTTPException(status_code=500, detail="Candidate Impact devolvió value no autorizado.")
    state = data.get("stateIntegrity")
    if not isinstance(state, dict):
        raise HTTPException(status_code=500, detail="Candidate Impact sellado perdió stateIntegrity.")
    state["callerSuppliedValueAccepted"] = False
    state["valueComparison"] = "blocked_until_candidate_has_matching_sealed_pit_value_evidence"
    return {"data": data}
