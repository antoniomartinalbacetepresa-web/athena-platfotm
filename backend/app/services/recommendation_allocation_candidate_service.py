from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from typing import Any, Protocol

from app.repositories.recommendation_allocation_policy_repository import (
    RecommendationAllocationPolicyRepository,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)


class _PolicyRepository(Protocol):
    def get(self, *, policy_id: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _EconomicContractValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationAllocationCandidateService:
    """Translate a validated action into a portfolio sleeve target, still non-advisory.

    The single-asset action exposure is never interpreted as a portfolio weight.
    Instead, a separately registered portfolio policy defines the maximum instrument
    sleeve. The frozen economic contract only determines where inside that sleeve the
    action points. Increasing exposure additionally requires fresh, PIT, pairwise
    correlation evidence against every other held instrument. De-risking actions are
    not blocked by missing correlation evidence.
    """

    ARTIFACT_VERSION = "athena-allocation-candidate-v1"
    ACTION_VERSION = "athena-uncertainty-bound-action-candidate-v1"

    def __init__(
        self,
        *,
        policy_repository: _PolicyRepository | None = None,
        economic_contract_validator: _EconomicContractValidator | None = None,
    ) -> None:
        self._policy_repository = (
            policy_repository or RecommendationAllocationPolicyRepository()
        )
        self._economic_contract_validator = (
            economic_contract_validator or RecommendationShadowActionEconomicContractService()
        )

    def build(
        self,
        *,
        uncertainty_bound_action_candidate: dict[str, Any],
        allocation_policy_id: str,
        economic_contract: dict[str, Any],
        reference_capital: float,
        base_currency: str,
        current_portfolio_value_base: float,
        current_position_value_base: float,
        portfolio_valuation_evidence_fingerprint: str,
        existing_position_instrument_ids: list[int],
        correlation_evidence: list[dict[str, Any]],
        as_of: datetime,
    ) -> dict[str, Any]:
        candidate = self._validated_action(uncertainty_bound_action_candidate)
        cutoff = self._aware_datetime(as_of, "as_of")
        reference = self._positive_finite(reference_capital, "reference_capital")
        portfolio_value = self._nonnegative_finite(
            current_portfolio_value_base, "current_portfolio_value_base"
        )
        position_value = self._nonnegative_finite(
            current_position_value_base, "current_position_value_base"
        )
        valuation_fp = self._sha256(
            portfolio_valuation_evidence_fingerprint,
            "portfolio_valuation_evidence_fingerprint",
        )

        policy_record = self._policy_repository.get(
            policy_id=self._text(allocation_policy_id, "allocation_policy_id")
        )
        if policy_record is None:
            raise ValueError("La política de asignación no está registrada.")
        if self._policy_repository.validate_record(policy_record) is not policy_record:
            raise ValueError("El repositorio sustituyó la política de asignación.")
        policy = policy_record.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El registro de asignación carece de policy válida.")
        currency = self._currency(base_currency, "base_currency")
        if currency != self._currency(policy.get("baseCurrency"), "policy.baseCurrency"):
            raise ValueError("La moneda base no coincide con la política de asignación.")

        validated_contract = self._economic_contract_validator.validate(economic_contract)
        if validated_contract is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")
        contract_fp = self._sha256(
            economic_contract.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )

        state = self._text(candidate.get("policyState"), "policyState")
        action = self._text(candidate.get("action"), "action").lower()
        self._validate_position_value_semantics(state=state, position_value=position_value)
        current_weight = position_value / reference
        if not math.isfinite(current_weight) or current_weight < 0.0:
            raise ValueError("El peso actual no es finito.")

        sleeve = self._unit(
            policy.get("maximumInstrumentSleeveWeight"),
            "maximumInstrumentSleeveWeight",
        )
        target_fraction = self._target_exposure_fraction(
            economic_contract=economic_contract,
            state=state,
            action=action,
        )
        target_weight = current_weight if action == "hold" else sleeve * target_fraction
        if not math.isfinite(target_weight) or target_weight < 0.0 or target_weight > 1.0:
            raise ValueError("El targetWeight resultante no es válido.")
        if target_weight > sleeve + 1e-12:
            raise ValueError("El targetWeight supera el sleeve permitido.")

        increasing = target_weight > current_weight + 1e-12
        held_ids = self._instrument_ids(existing_position_instrument_ids)
        instrument_id = self._positive_int(candidate.get("instrumentId"), "instrumentId")
        others = sorted(item for item in held_ids if item != instrument_id)
        correlation_checks = self._validate_correlations(
            evidence=correlation_evidence,
            candidate_instrument_id=instrument_id,
            other_instrument_ids=others,
            cutoff=cutoff,
            policy=policy,
            required=increasing,
        )

        target_amount = reference * target_weight
        current_amount = position_value
        delta_amount = target_amount - current_amount
        excess = max(portfolio_value - reference, 0.0)
        shortfall = max(reference - portfolio_value, 0.0)
        reserve_weight = self._unit(
            policy.get("minimumCashReserveWeight"), "minimumCashReserveWeight"
        )
        if target_weight > 1.0 - reserve_weight + 1e-12:
            raise ValueError("El target viola la reserva mínima de efectivo.")

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "uncertaintyBoundActionCandidateFingerprint": self._sha256(
                candidate.get("uncertaintyBoundActionCandidateFingerprint"),
                "uncertaintyBoundActionCandidateFingerprint",
            ),
            "allocationPolicyId": policy.get("policyId"),
            "allocationPolicyFingerprint": self._sha256(
                policy.get("policyFingerprint"), "policyFingerprint"
            ),
            "economicContractFingerprint": contract_fp,
            "portfolioValuationEvidenceFingerprint": valuation_fp,
            "instrumentId": instrument_id,
            "symbol": candidate.get("symbol"),
            "asOf": cutoff.isoformat(),
            "baseCurrency": currency,
            "action": action,
            "policyState": state,
            "referenceCapital": reference,
            "currentPortfolioValueInBaseCurrency": portfolio_value,
            "excessOverReferenceCapital": excess,
            "shortfallVsReferenceCapital": shortfall,
            "currentPositionValueInBaseCurrency": current_amount,
            "currentPositionWeightVsReferenceCapital": current_weight,
            "maximumInstrumentSleeveWeight": sleeve,
            "singleAssetTargetExposureFraction": target_fraction,
            "targetWeight": target_weight,
            "targetAmountInBaseCurrency": target_amount,
            "deltaAmountInBaseCurrency": delta_amount,
            "increasesExposure": increasing,
            "correlationChecks": correlation_checks,
        }
        return {
            "status": "allocation_candidate_non_advisory",
            **core,
            "allocationCandidateFingerprint": self._fingerprint(core),
            "allocationEvidenceStructurallyReady": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "referenceCapitalSemantics": "user_owned_allocation_base_not_market_value",
                "excessOverReferenceCapitalShownExplicitly": True,
                "singleAssetExposureMappedOnlyInsideInstrumentSleeve": True,
                "correlationRequiredOnlyWhenIncreasingExposure": True,
                "deRiskingNeverBlockedByMissingCorrelation": True,
                "verifiedIdentityFxAndPortfolioRiskPromotionStillRequired": True,
                "automaticTrading": False,
            },
        }

    def _validated_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("artifactVersion") != self.ACTION_VERSION:
            raise ValueError("Versión de candidato de acción/incertidumbre no compatible.")
        if payload.get("status") != "uncertainty_bound_action_candidate_non_advisory":
            raise ValueError("Se exige un candidato ligado a incertidumbre.")
        if payload.get("uncertaintyBoundActionEvidenceReady") is not True:
            raise ValueError("La evidencia acción/incertidumbre no está preparada.")
        for field in ("recommendationCandidateReady", "productionEligible", "allocationEligible"):
            if payload.get(field) is not False:
                raise ValueError(f"El candidato violó {field}=False.")
        if payload.get("advisoryStatus") != "no_advice" or payload.get("automaticTrading") is not False:
            raise ValueError("El candidato debe permanecer no_advice y sin trading.")
        core_keys = (
            "artifactVersion",
            "validatedActionCandidateFingerprint",
            "actionUncertaintyEvidenceFingerprint",
            "actionPromotionDecisionId",
            "actionPromotionDecisionFingerprint",
            "candidateFingerprint",
            "instrumentId",
            "symbol",
            "asOf",
            "horizonDays",
            "modelFingerprint",
            "policyState",
            "policyFingerprint",
            "portfolioPolicyStateFingerprint",
            "action",
        )
        core = {key: payload.get(key) for key in core_keys}
        supplied = self._sha256(
            payload.get("uncertaintyBoundActionCandidateFingerprint"),
            "uncertaintyBoundActionCandidateFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("El candidato acción/incertidumbre fue modificado.")
        return payload

    def _target_exposure_fraction(
        self,
        *,
        economic_contract: dict[str, Any],
        state: str,
        action: str,
    ) -> float:
        actions = economic_contract.get("actions")
        states = economic_contract.get("positionStates")
        if not isinstance(actions, dict) or not isinstance(states, dict):
            raise ValueError("El contrato económico carece de estados/acciones.")
        action_payload = actions.get(action)
        if not isinstance(action_payload, dict):
            raise ValueError("La acción no pertenece al contrato económico.")
        allowed = action_payload.get("allowedFrom")
        if not isinstance(allowed, list) or state not in allowed:
            raise ValueError("La acción no está permitida desde el estado actual.")
        target = action_payload.get("targetExposureFraction")
        if target == "unchanged":
            state_payload = states.get(state)
            if not isinstance(state_payload, dict):
                raise ValueError("El estado actual no está definido.")
            return self._unit(
                state_payload.get("targetExposureFraction"),
                "currentTargetExposureFraction",
            )
        return self._unit(target, "targetExposureFraction")

    def _validate_position_value_semantics(self, *, state: str, position_value: float) -> None:
        if state == "flat":
            if position_value != 0.0:
                raise ValueError("El estado flat exige valor de posición exactamente cero.")
            return
        if state in {"reduced_long", "full_long"}:
            if position_value <= 0.0:
                raise ValueError("Un estado long exige una posición real con valor positivo.")
            return
        raise ValueError("policyState no soportado.")

    def _validate_correlations(
        self,
        *,
        evidence: list[dict[str, Any]],
        candidate_instrument_id: int,
        other_instrument_ids: list[int],
        cutoff: datetime,
        policy: dict[str, Any],
        required: bool,
    ) -> list[dict[str, Any]]:
        if not isinstance(evidence, list):
            raise ValueError("correlation_evidence debe ser una lista.")
        if not required:
            return []
        if not other_instrument_ids:
            if evidence:
                raise ValueError("Se recibió correlación sin otras posiciones que comprobar.")
            return []
        maximum = self._unit(
            policy.get("maximumAbsolutePairCorrelation"),
            "maximumAbsolutePairCorrelation",
        )
        minimum_samples = self._positive_int(
            policy.get("minimumCorrelationSampleCount"),
            "minimumCorrelationSampleCount",
        )
        maximum_age = self._positive_int(
            policy.get("maximumCorrelationAgeSeconds"),
            "maximumCorrelationAgeSeconds",
        )
        by_other: dict[int, dict[str, Any]] = {}
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Una evidencia de correlación no es objeto.")
            left = self._positive_int(item.get("leftInstrumentId"), "leftInstrumentId")
            right = self._positive_int(item.get("rightInstrumentId"), "rightInstrumentId")
            pair = {left, right}
            if candidate_instrument_id not in pair or len(pair) != 2:
                raise ValueError("La correlación no corresponde al instrumento candidato.")
            other = right if left == candidate_instrument_id else left
            if other not in other_instrument_ids:
                raise ValueError("La correlación corresponde a una posición no declarada.")
            if other in by_other:
                raise ValueError("Existe correlación duplicada para una posición.")
            provider = self._text(item.get("sourceProvider"), "sourceProvider")
            knowledge_cutoff = self._aware_text(item.get("knowledgeCutoff"), "knowledgeCutoff")
            if knowledge_cutoff != cutoff:
                raise ValueError("La correlación no comparte el mismo knowledge cutoff.")
            latest_retrieved = self._aware_text(
                item.get("latestRetrievedAt"), "latestRetrievedAt"
            )
            if latest_retrieved > cutoff:
                raise ValueError("La correlación utiliza datos recuperados después de as_of.")
            sample_count = self._positive_int(item.get("sampleCount"), "sampleCount")
            if sample_count < minimum_samples:
                raise ValueError("La correlación no alcanza la muestra mínima preespecificada.")
            correlation = self._finite(item.get("correlation"), "correlation")
            if correlation < -1.0 or correlation > 1.0:
                raise ValueError("La correlación está fuera de [-1,1].")
            if abs(correlation) > maximum:
                raise ValueError("La correlación supera el límite preespecificado.")
            last_date = self._date(item.get("lastReturnDate"), "lastReturnDate")
            last_dt = datetime.combine(last_date, time.max, tzinfo=timezone.utc)
            age_seconds = (cutoff - last_dt).total_seconds()
            if age_seconds < 0:
                raise ValueError("lastReturnDate es posterior al knowledge cutoff.")
            if age_seconds > maximum_age:
                raise ValueError("La correlación está stale según la política registrada.")
            by_other[other] = {
                "otherInstrumentId": other,
                "sourceProvider": provider,
                "knowledgeCutoff": knowledge_cutoff.isoformat(),
                "sampleCount": sample_count,
                "correlation": correlation,
                "lastReturnDate": last_date.isoformat(),
                "latestRetrievedAt": latest_retrieved.isoformat(),
                "passesPolicy": True,
            }
        if set(by_other) != set(other_instrument_ids):
            raise ValueError("Falta correlación PIT verificable para alguna posición existente.")
        return [by_other[item] for item in sorted(by_other)]

    def _instrument_ids(self, values: object) -> set[int]:
        if not isinstance(values, list):
            raise ValueError("existing_position_instrument_ids debe ser lista.")
        result = {self._positive_int(value, "existing_position_instrument_ids") for value in values}
        if len(result) != len(values):
            raise ValueError("existing_position_instrument_ids contiene duplicados.")
        return result

    def _date(self, value: object, field: str) -> date:
        raw = self._text(value, field)
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser fecha ISO.") from exc

    def _aware_text(self, value: object, field: str) -> datetime:
        raw = self._text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601.") from exc
        return self._aware_datetime(parsed, field)

    def _aware_datetime(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _currency(self, value: object, field: str) -> str:
        result = str(value or "").strip().upper()
        if len(result) != 3 or any(ch < "A" or ch > "Z" for ch in result):
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _unit(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0 or result > 1.0:
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        return result

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _nonnegative_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0:
            raise ValueError(f"{field} debe ser no negativo.")
        return result

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        try:
            canonical = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El artefacto contiene valores no finitos/no serializables.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
