from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_portfolio_valuation_evidence_repository import (
    RecommendationPortfolioValuationEvidenceRepository,
)
from app.services.recommendation_allocation_candidate_service import (
    RecommendationAllocationCandidateService,
)
from app.services.recommendation_portfolio_valuation_evidence_service import (
    RecommendationPortfolioValuationEvidenceService,
)


class _ValuationService(Protocol):
    def build(
        self,
        *,
        positions: list[dict[str, Any]],
        base_currency: str,
        as_of: datetime,
    ) -> dict[str, Any]: ...

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _ValuationRepository(Protocol):
    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _AllocationService(Protocol):
    def build(self, **kwargs: Any) -> dict[str, Any]: ...


class RecommendationVerifiedAllocationPipelineService:
    """Derive allocation inputs from sealed PIT portfolio evidence.

    Callers supply position observations, not valuation totals. The pipeline rebuilds
    invested-position market value from canonical identity, PIT prices and PIT FX,
    validates and seals that exact valuation in the append-only evidence repository,
    derives the candidate instrument's current value and held-instrument set, and only
    then invokes the allocation engine. This prevents the verified path from accepting
    caller-invented portfolio/position values, a free-standing SHA, or an unpersisted
    valuation as allocation provenance.

    The resulting artifact remains explicitly non-advisory and non-executable. Its
    portfolio-value scope is invested positions only; cash, liabilities and broker NAV
    are not inferred.
    """

    ARTIFACT_VERSION = "athena-verified-allocation-pipeline-v2"

    def __init__(
        self,
        *,
        valuation_service: _ValuationService | None = None,
        valuation_repository: _ValuationRepository | None = None,
        allocation_service: _AllocationService | None = None,
    ) -> None:
        self._valuation_service = (
            valuation_service or RecommendationPortfolioValuationEvidenceService()
        )
        self._valuation_repository = (
            valuation_repository
            or RecommendationPortfolioValuationEvidenceRepository(
                validator=self._valuation_service,
            )
        )
        self._allocation_service = (
            allocation_service or RecommendationAllocationCandidateService()
        )

    def build(
        self,
        *,
        uncertainty_bound_action_candidate: dict[str, Any],
        allocation_policy_id: str,
        economic_contract: dict[str, Any],
        reference_capital: float,
        base_currency: str,
        positions: list[dict[str, Any]],
        correlation_evidence: list[dict[str, Any]],
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware_datetime(as_of, "as_of")
        if not isinstance(uncertainty_bound_action_candidate, dict):
            raise ValueError("uncertainty_bound_action_candidate debe ser un objeto.")
        candidate_as_of = self._aware_text(
            uncertainty_bound_action_candidate.get("asOf"), "candidate.asOf"
        )
        if candidate_as_of != cutoff:
            raise ValueError("El candidato y la valoración deben compartir exactamente as_of.")
        instrument_id = self._positive_int(
            uncertainty_bound_action_candidate.get("instrumentId"),
            "candidate.instrumentId",
        )

        valuation = self._valuation_service.build(
            positions=positions,
            base_currency=base_currency,
            as_of=cutoff,
        )
        if self._valuation_service.validate_artifact(valuation) is not valuation:
            raise ValueError("El validador sustituyó la evidencia de valoración.")
        if valuation.get("portfolioValuationEvidenceReady") is not True:
            raise ValueError("La valoración PIT no está preparada.")
        if valuation.get("advisoryStatus") != "no_advice":
            raise ValueError("La valoración intentó emitir advice.")
        if valuation.get("productionEligible") is not False:
            raise ValueError("La valoración intentó habilitar producción.")
        if valuation.get("automaticTrading") is not False:
            raise ValueError("La valoración intentó habilitar trading.")
        if self._aware_text(valuation.get("asOf"), "valuation.asOf") != cutoff:
            raise ValueError("La valoración cambió el corte temporal.")
        currency = self._currency(base_currency, "base_currency")
        if self._currency(valuation.get("baseCurrency"), "valuation.baseCurrency") != currency:
            raise ValueError("La valoración cambió la moneda base.")
        if valuation.get("cashIncluded") is not False or valuation.get("liabilitiesIncluded") is not False:
            raise ValueError("El alcance de valoración no coincide con invested positions only.")
        if valuation.get("valuationScope") != (
            "invested_long_positions_only_cash_liabilities_unsettled_excluded"
        ):
            raise ValueError("El alcance de valoración no está soportado por este pipeline.")

        valuation_record = self._valuation_repository.seal(artifact=valuation)
        if not isinstance(valuation_record, dict):
            raise ValueError("El repositorio no devolvió un registro de valoración válido.")
        if self._valuation_repository.validate_record(valuation_record) is not valuation_record:
            raise ValueError("El repositorio sustituyó el registro de valoración sellado.")
        persisted_valuation = valuation_record.get("artifact")
        if not isinstance(persisted_valuation, dict):
            raise ValueError("El registro sellado carece de valoración PIT.")
        if persisted_valuation != valuation:
            raise ValueError("La valoración sellada difiere del artefacto validado.")
        valuation = persisted_valuation
        valuation_record_fingerprint = self._sha256(
            valuation_record.get("record_fingerprint"),
            "portfolioValuationRecordFingerprint",
        )
        valuation_persisted_at = self._aware_text(
            valuation_record.get("persisted_at"),
            "portfolioValuationPersistedAt",
        )

        valuation_positions = valuation.get("positions")
        if not isinstance(valuation_positions, list):
            raise ValueError("La valoración carece de posiciones verificables.")
        existing_ids: list[int] = []
        current_position_value = 0.0
        seen: set[int] = set()
        for payload in valuation_positions:
            if not isinstance(payload, dict):
                raise ValueError("La valoración contiene una posición inválida.")
            held_id = self._positive_int(payload.get("instrumentId"), "position.instrumentId")
            if held_id in seen:
                raise ValueError("La valoración contiene instrumentId duplicado.")
            seen.add(held_id)
            existing_ids.append(held_id)
            value = self._nonnegative_finite(
                payload.get("positionValueInBaseCurrency"),
                "position.positionValueInBaseCurrency",
            )
            if held_id == instrument_id:
                current_position_value = value

        portfolio_value = self._nonnegative_finite(
            valuation.get("investedPositionsValueInBaseCurrency"),
            "investedPositionsValueInBaseCurrency",
        )
        recomputed = sum(
            self._nonnegative_finite(
                payload.get("positionValueInBaseCurrency"),
                "position.positionValueInBaseCurrency",
            )
            for payload in valuation_positions
        )
        if not math.isclose(recomputed, portfolio_value, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("La valoración agregada no coincide con sus posiciones.")

        valuation_fp = self._sha256(
            valuation.get("portfolioValuationEvidenceFingerprint"),
            "portfolioValuationEvidenceFingerprint",
        )
        if valuation_record.get("valuation_fingerprint") != valuation_fp:
            raise ValueError("El registro sellado no corresponde al fingerprint de valoración.")
        if self._aware_text(valuation_record.get("as_of"), "valuationRecord.as_of") != cutoff:
            raise ValueError("El registro sellado cambió el corte temporal.")
        if self._currency(
            valuation_record.get("base_currency"), "valuationRecord.base_currency"
        ) != currency:
            raise ValueError("El registro sellado cambió la moneda base.")

        allocation = self._allocation_service.build(
            uncertainty_bound_action_candidate=uncertainty_bound_action_candidate,
            allocation_policy_id=allocation_policy_id,
            economic_contract=economic_contract,
            reference_capital=reference_capital,
            base_currency=currency,
            current_portfolio_value_base=portfolio_value,
            current_position_value_base=current_position_value,
            portfolio_valuation_evidence_fingerprint=valuation_fp,
            existing_position_instrument_ids=existing_ids,
            correlation_evidence=correlation_evidence,
            as_of=cutoff,
        )
        self._assert_allocation_binding(
            allocation=allocation,
            valuation_fingerprint=valuation_fp,
            portfolio_value=portfolio_value,
            current_position_value=current_position_value,
            cutoff=cutoff,
            currency=currency,
        )

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "asOf": cutoff.isoformat(),
            "baseCurrency": currency,
            "instrumentId": instrument_id,
            "portfolioValuationEvidenceFingerprint": valuation_fp,
            "portfolioValuationRecordFingerprint": valuation_record_fingerprint,
            "portfolioValuationPersistedAt": valuation_persisted_at.isoformat(),
            "allocationCandidateFingerprint": self._sha256(
                allocation.get("allocationCandidateFingerprint"),
                "allocationCandidateFingerprint",
            ),
            "portfolioValueScope": valuation.get("valuationScope"),
            "cashIncluded": False,
            "liabilitiesIncluded": False,
            "investedPositionsValueInBaseCurrency": portfolio_value,
            "currentPositionValueInBaseCurrency": current_position_value,
            "existingPositionInstrumentIds": sorted(existing_ids),
        }
        return {
            "status": "verified_allocation_pipeline_non_advisory",
            **core,
            "verifiedAllocationPipelineFingerprint": self._fingerprint(core),
            "portfolioValuationEvidence": valuation,
            "portfolioValuationPersistence": {
                "sealed": True,
                "persistedAt": valuation_persisted_at.isoformat(),
                "recordFingerprint": valuation_record_fingerprint,
            },
            "allocationCandidate": allocation,
            "portfolioValuationBoundToAllocation": True,
            "portfolioValuationSealedBeforeAllocation": True,
            "callerSuppliedValuationTotalsAccepted": False,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "portfolioTotalsDerivedInternallyFromPitEvidence": True,
                "portfolioValuationMustBeAppendOnlySealedBeforeAllocation": True,
                "currentPositionValueDerivedInternally": True,
                "heldInstrumentIdsDerivedInternally": True,
                "cashMustNotBeInferred": True,
                "brokerNetLiquidationValueNotClaimed": True,
                "referenceCapitalRemainsUserOwnedAllocationBase": True,
                "automaticTrading": False,
            },
        }

    def _assert_allocation_binding(
        self,
        *,
        allocation: object,
        valuation_fingerprint: str,
        portfolio_value: float,
        current_position_value: float,
        cutoff: datetime,
        currency: str,
    ) -> None:
        if not isinstance(allocation, dict):
            raise ValueError("El motor de asignación no devolvió un artefacto válido.")
        if allocation.get("status") != "allocation_candidate_non_advisory":
            raise ValueError("La asignación no permanece en estado no advisory.")
        if allocation.get("portfolioValuationEvidenceFingerprint") != valuation_fingerprint:
            raise ValueError("La asignación no quedó ligada a la valoración PIT.")
        if self._aware_text(allocation.get("asOf"), "allocation.asOf") != cutoff:
            raise ValueError("La asignación cambió el corte temporal.")
        if self._currency(allocation.get("baseCurrency"), "allocation.baseCurrency") != currency:
            raise ValueError("La asignación cambió la moneda base.")
        if not math.isclose(
            self._nonnegative_finite(
                allocation.get("currentPortfolioValueInBaseCurrency"),
                "allocation.currentPortfolioValueInBaseCurrency",
            ),
            portfolio_value,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("La asignación alteró el valor agregado verificado.")
        if not math.isclose(
            self._nonnegative_finite(
                allocation.get("currentPositionValueInBaseCurrency"),
                "allocation.currentPositionValueInBaseCurrency",
            ),
            current_position_value,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("La asignación alteró el valor de posición verificado.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "allocationEligible",
            "automaticTrading",
        ):
            if allocation.get(field) is not False:
                raise ValueError(f"La asignación violó {field}=False.")
        if allocation.get("advisoryStatus") != "no_advice":
            raise ValueError("La asignación intentó emitir advice.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _nonnegative_finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result) or result < 0.0:
            raise ValueError(f"{field} debe ser finito y no negativo.")
        return result

    def _aware_text(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser fecha ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha ISO válida.") from exc
        return self._aware_datetime(parsed, field)

    def _aware_datetime(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _currency(self, value: object, field: str) -> str:
        result = str(value or "").strip().upper()
        if len(result) != 3 or not result.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
