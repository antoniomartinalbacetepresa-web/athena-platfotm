from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)
from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.recommendation_factor_risk_candidate_impact_service import (
    RecommendationFactorRiskCandidateImpactService,
)
from app.services.recommendation_factor_risk_service import FactorRiskPositionInput
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


router = APIRouter(
    prefix="/api/v1/recommendations/professional-research",
    tags=["recommendations-professional-research"],
)

candidate_impact_service = RecommendationFactorRiskCandidateImpactService()
_reconciliation_repository = RecommendationPortfolioStateReconciliationRepository()
_valuation_repository = RecommendationPortfolioValuationEvidenceRepository()
_weight_service = RecommendationReconciledPortfolioWeightService()
_SEALED_CALLER_FORBIDDEN = {"market", "momentum", "low_volatility", "size", "usd_fx"}


class BaselineFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class CandidateFactorExposureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrumentId: int = Field(gt=0)
    symbol: str = Field(min_length=1)
    weight: float = Field(gt=0.0, le=1.0)
    exposureAvailableAt: datetime
    source: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    factors: dict[str, float] = Field(min_length=1)


class FactorRiskCandidateImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolioId: str = Field(min_length=1)
    reportingCurrency: str = Field(min_length=3, max_length=3)
    reconciliationKey: str = Field(min_length=64, max_length=64)
    portfolioValuationEvidenceFingerprint: str = Field(min_length=64, max_length=64)
    asOf: datetime
    positions: list[BaselineFactorExposureRequest] = Field(min_length=1, max_length=499)
    candidate: CandidateFactorExposureRequest


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


def _reject_sealed_caller_factors(factors: dict[str, float], field: str) -> None:
    normalized = {str(name).strip().lower() for name in factors}
    forbidden = sorted(normalized & _SEALED_CALLER_FORBIDDEN)
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} no puede suministrar factores sellados {forbidden}; "
                "Candidate Impact no los comparará hasta disponer de evidencia PIT sellada del candidato."
            ),
        )


def _assert_contract(payload: dict[str, object]) -> None:
    if payload.get("advisoryStatus") != "no_advice":
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact violó no-advice.")
    if payload.get("productionEligible") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact intentó habilitar producción.")
    if payload.get("isWeightingReady") is not False:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact intentó habilitar ponderación.")

    state_integrity = payload.get("stateIntegrity")
    if not isinstance(state_integrity, dict):
        raise HTTPException(status_code=500, detail="Candidate Impact perdió stateIntegrity.")
    if state_integrity.get("baselineWeightDerivation") != "derived_from_reconciled_state_and_sealed_pit_valuation":
        raise HTTPException(status_code=500, detail="Candidate Impact no derivó baseline desde evidencia reconciliada.")
    if state_integrity.get("baselineCallerSuppliedWeightAccepted") is not False:
        raise HTTPException(status_code=500, detail="Candidate Impact aceptó pesos baseline arbitrarios.")
    if state_integrity.get("callerSuppliedSealedFactorsAccepted") is not False:
        raise HTTPException(status_code=500, detail="Candidate Impact aceptó factores sellados arbitrarios.")
    if state_integrity.get("sealedFactorComparison") != "blocked_until_candidate_has_matching_sealed_pit_evidence":
        raise HTTPException(status_code=500, detail="Candidate Impact perdió la frontera de factores sellados.")
    if state_integrity.get("candidateWeightMeaning") != "explicit_hypothetical_cash_funded_scenario_not_sizing_advice":
        raise HTTPException(status_code=500, detail="Candidate Impact perdió semántica hipotética del candidato.")
    if state_integrity.get("reconciled") is not True or state_integrity.get("tamperVerified") is not True:
        raise HTTPException(status_code=500, detail="Candidate Impact aceptó estado no reconciliado/verificado.")
    for field in (
        "reconciliationKey",
        "portfolioStateKey",
        "portfolioValuationEvidenceFingerprint",
        "weightEvidenceKey",
    ):
        value = state_integrity.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise HTTPException(status_code=500, detail=f"Candidate Impact perdió {field} válido.")

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió política inválida.")
    expected_policy = {
        "funding": "candidate_weight_is_explicit_caller_input_and_must_be_funded_from_existing_cash",
        "comparison": "only_factors_fully_covered_before_and_after_are_compared",
        "missingFactorCoverage": "coverage_loss_is_reported_never_imputed_as_zero",
        "covariance": "not_estimated_no_marginal_variance_or_risk_contribution_claim",
        "fx": "usd_fx_remains_explicit_and_is_never_silently_hedged",
        "thresholds": "not_calibrated",
        "interpretation": "candidate_factor_exposure_impact_not_position_sizing_or_trade_advice",
        "automaticTrading": False,
        "automaticProductionPromotion": False,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            raise HTTPException(status_code=500, detail=f"Factor Risk Candidate Impact perdió garantía: {key}.")

    numeric_fields = (
        "baselineInvestedWeight",
        "baselineCashWeight",
        "postInvestedWeight",
        "postCashWeight",
        "baselineComparableGrossExposure",
        "postComparableGrossExposure",
        "comparableGrossExposureDelta",
        "baselineComparableMaxAbsExposure",
        "postComparableMaxAbsExposure",
        "comparableMaxAbsExposureDelta",
    )
    if any(not _finite_number(payload.get(field)) for field in numeric_fields):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió métricas no finitas.")
    if abs(float(payload["baselineInvestedWeight"]) + float(payload["baselineCashWeight"]) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió baseline incoherente.")
    if abs(float(payload["postInvestedWeight"]) + float(payload["postCashWeight"]) - 1.0) > 1e-9:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió post-cartera incoherente.")
    if float(payload["postInvestedWeight"]) <= float(payload["baselineInvestedWeight"]):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact perdió el incremento explícito de inversión.")
    if float(payload["postCashWeight"]) >= float(payload["baselineCashWeight"]):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact no refleja financiación desde efectivo.")
    if not math.isclose(
        float(payload["baselineCashWeight"]),
        float(state_integrity.get("baselineCashWeight")),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise HTTPException(status_code=500, detail="Candidate Impact no reconcilió cash baseline derivado.")

    comparable = payload.get("comparableFactors")
    coverage_lost = payload.get("coverageLostFactors")
    before = payload.get("baselineWeightedExposures")
    after = payload.get("postWeightedExposures")
    deltas = payload.get("factorExposureDeltas")
    if (
        not isinstance(comparable, list)
        or not comparable
        or any(not isinstance(name, str) or not name for name in comparable)
        or not isinstance(coverage_lost, list)
        or any(not isinstance(name, str) or not name for name in coverage_lost)
        or not isinstance(before, dict)
        or not isinstance(after, dict)
        or not isinstance(deltas, dict)
    ):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió comparación inválida.")
    if len(set(comparable)) != len(comparable) or set(comparable) & set(coverage_lost):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió factores incoherentes.")
    if set(before) != set(comparable) or set(after) != set(comparable) or set(deltas) != set(comparable):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió mapas factoriales incompletos.")
    for factor in comparable:
        if factor in _SEALED_CALLER_FORBIDDEN:
            raise HTTPException(status_code=500, detail="Candidate Impact devolvió comparación de factor sellado sin evidencia sellada.")
        values = (before.get(factor), after.get(factor), deltas.get(factor))
        if any(not _finite_number(value) for value in values):
            raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió exposición no finita.")
        if abs((float(after[factor]) - float(before[factor])) - float(deltas[factor])) > 1e-9:
            raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió delta factorial incoherente.")

    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact perdió evidencia del candidato.")
    required_candidate = (
        "instrumentId",
        "symbol",
        "weight",
        "exposureAvailableAt",
        "source",
        "sourceRef",
        "factors",
    )
    if any(candidate.get(field) in (None, "") for field in required_candidate):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió provenance PIT incompleta.")
    if not _finite_number(candidate.get("weight")) or float(candidate["weight"]) <= 0.0:
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió peso de candidato inválido.")
    factors = candidate.get("factors")
    if not isinstance(factors, dict) or not factors or any(not _finite_number(value) for value in factors.values()):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió factores de candidato inválidos.")
    if {str(name).strip().lower() for name in factors} & _SEALED_CALLER_FORBIDDEN:
        raise HTTPException(status_code=500, detail="Candidate Impact devolvió factor sellado no autorizado en candidato.")


@router.post("/factor-risk/candidate-impact")
def post_factor_risk_candidate_impact(
    request: FactorRiskCandidateImpactRequest,
) -> dict[str, object]:
    """Measure a hypothetical cash-funded candidate against a reconciled PIT baseline."""

    as_of = _aware_utc(request.asOf, "asOf")
    for index, item in enumerate(request.positions):
        _reject_sealed_caller_factors(item.factors, f"positions[{index}].factors")
    _reject_sealed_caller_factors(request.candidate.factors, "candidate.factors")

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
            detail="No se pudo derivar baseline reconciliado para Candidate Impact.",
        ) from exc

    if weight_evidence["portfolioId"] != request.portfolioId.strip():
        raise HTTPException(status_code=400, detail="Weight evidence pertenece a otra cartera.")
    if weight_evidence["reportingCurrency"] != request.reportingCurrency.strip().upper():
        raise HTTPException(status_code=400, detail="Weight evidence usa otra moneda.")
    if datetime.fromisoformat(str(weight_evidence["asOf"]).replace("Z", "+00:00")) != as_of:
        raise HTTPException(status_code=400, detail="Weight evidence pertenece a otro asOf.")

    derived_positions = weight_evidence.get("positions")
    if not isinstance(derived_positions, list):
        raise HTTPException(status_code=500, detail="Weight evidence perdió positions.")
    by_id: dict[int, dict[str, object]] = {}
    for position in derived_positions:
        if not isinstance(position, dict):
            raise HTTPException(status_code=500, detail="Weight evidence contiene posición inválida.")
        instrument_id = position.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise HTTPException(status_code=500, detail="Weight evidence perdió instrumentId.")
        if instrument_id in by_id:
            raise HTTPException(status_code=500, detail="Weight evidence duplicó instrumentId.")
        by_id[instrument_id] = position

    request_ids = [item.instrumentId for item in request.positions]
    if len(request_ids) != len(set(request_ids)):
        raise HTTPException(status_code=400, detail="Baseline factor exposures contiene instrumentId duplicado.")
    if set(request_ids) != set(by_id):
        missing = sorted(set(by_id) - set(request_ids))
        extra = sorted(set(request_ids) - set(by_id))
        raise HTTPException(
            status_code=400,
            detail=f"Baseline factor identity mismatch; missing={missing}, extra={extra}.",
        )
    if request.candidate.instrumentId in by_id:
        raise HTTPException(
            status_code=400,
            detail="Candidate instrumentId ya pertenece a la cartera baseline; este endpoint no modela aumentos de posición existentes.",
        )

    positions: list[FactorRiskPositionInput] = []
    for item in request.positions:
        derived = by_id[item.instrumentId]
        symbol = str(derived.get("symbol") or "").strip().upper()
        if item.symbol.strip().upper() != symbol:
            raise HTTPException(status_code=400, detail="Símbolo baseline no coincide con valoración canónica.")
        weight = derived.get("weight")
        if not _finite_number(weight):
            raise HTTPException(status_code=500, detail="Weight evidence devolvió peso baseline no finito.")
        positions.append(
            FactorRiskPositionInput(
                instrument_id=item.instrumentId,
                symbol=symbol,
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

    candidate = FactorRiskPositionInput(
        instrument_id=request.candidate.instrumentId,
        symbol=request.candidate.symbol,
        weight=request.candidate.weight,
        exposure_available_at=_aware_utc(
            request.candidate.exposureAvailableAt,
            "candidate.exposureAvailableAt",
        ),
        source=request.candidate.source,
        source_ref=request.candidate.sourceRef,
        factors=dict(request.candidate.factors),
    )

    try:
        result = candidate_impact_service.evaluate(
            as_of=as_of,
            positions=tuple(positions),
            candidate=candidate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo evaluar el impacto factorial PIT del candidato.",
        ) from exc

    payload = result.to_api_dict()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Factor Risk Candidate Impact devolvió contrato inválido.")
    payload["stateIntegrity"] = {
        "reconciliationKey": str(weight_evidence["reconciliationKey"]),
        "portfolioStateKey": str(weight_evidence["portfolioStateKey"]),
        "portfolioValuationEvidenceFingerprint": str(
            weight_evidence["portfolioValuationEvidenceFingerprint"]
        ),
        "weightEvidenceKey": str(weight_evidence["weightEvidenceKey"]),
        "reconciled": True,
        "tamperVerified": True,
        "baselineCashWeight": weight_evidence["cashWeight"],
        "baselineWeightDerivation": "derived_from_reconciled_state_and_sealed_pit_valuation",
        "baselineCallerSuppliedWeightAccepted": False,
        "callerSuppliedSealedFactorsAccepted": False,
        "sealedFactorComparison": "blocked_until_candidate_has_matching_sealed_pit_evidence",
        "candidateWeightMeaning": "explicit_hypothetical_cash_funded_scenario_not_sizing_advice",
    }
    _assert_contract(payload)
    return {"data": payload}
