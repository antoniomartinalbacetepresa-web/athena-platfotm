from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_action_uncertainty_protocol_repository import (
    RecommendationActionUncertaintyProtocolRepository,
)
from app.repositories.recommendation_shadow_action_threshold_selection_repository import (
    RecommendationShadowActionThresholdSelectionRepository,
)
from app.services.recommendation_shadow_action_calibration_dataset_service import (
    RecommendationShadowActionCalibrationDatasetService,
)
from app.services.recommendation_shadow_action_economic_contract_service import (
    RecommendationShadowActionEconomicContractService,
)
from app.services.recommendation_shadow_action_economic_utility_service import (
    RecommendationShadowActionEconomicUtilityService,
)


class _ProtocolRepository(Protocol):
    def get(self, *, protocol_id: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _SelectionRepository(Protocol):
    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _DatasetService(Protocol):
    def build(
        self,
        *,
        as_of: datetime,
        symbol: str | None = None,
        horizons: tuple[int, ...] | list[int],
    ) -> dict[str, Any]: ...


class _ContractValidator(Protocol):
    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class _UtilityService(Protocol):
    def evaluate(
        self,
        *,
        economic_contract: dict[str, Any],
        current_state: str,
        realized_excess_return: float,
    ) -> dict[str, Any]: ...


class RecommendationActionUncertaintyEvidenceService:
    """Gate promoted action policies with precommitted uncertainty criteria.

    The first future confirmation currently seals means but not dispersion. This
    service reconstructs the exact first-seal PIT window from immutable live-shadow
    rows, proves that its counts and means reproduce the sealed confirmation, then
    computes a sample standard error for incremental utility versus HOLD. The
    confidence multiplier and minimum acceptable lower bound come only from the
    append-only protocol registered before the policy freeze.

    The lower bound is a protocol-defined uncertainty guard, not a probability
    guarantee. Passing this gate remains non-advisory and cannot authorize allocation
    or trading.
    """

    ARTIFACT_VERSION = "athena-action-uncertainty-evidence-v1"
    CONFIRMATION_VERSION = "shadow-action-threshold-future-confirmation-v1"
    DATASET_VERSION = "shadow-action-calibration-v2"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(
        self,
        *,
        protocol_repository: _ProtocolRepository | None = None,
        selection_repository: _SelectionRepository | None = None,
        dataset_service: _DatasetService | None = None,
        contract_validator: _ContractValidator | None = None,
        utility_service: _UtilityService | None = None,
    ) -> None:
        self._protocol_repository = (
            protocol_repository or RecommendationActionUncertaintyProtocolRepository()
        )
        self._selection_repository = (
            selection_repository or RecommendationShadowActionThresholdSelectionRepository()
        )
        self._dataset_service = (
            dataset_service or RecommendationShadowActionCalibrationDatasetService()
        )
        self._contract_validator = (
            contract_validator or RecommendationShadowActionEconomicContractService()
        )
        self._utility_service = (
            utility_service or RecommendationShadowActionEconomicUtilityService()
        )

    def evaluate_registered(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
        economic_contract: dict[str, Any],
        symbol: str | None = None,
    ) -> dict[str, Any]:
        confirmation = self._validated_confirmation(confirmation_artifact)
        protocol_record = self._protocol_repository.get(
            protocol_id=self._text(protocol_id, "protocol_id")
        )
        if protocol_record is None:
            raise ValueError("El protocolo de incertidumbre no está registrado.")
        if self._protocol_repository.validate_record(protocol_record) is not protocol_record:
            raise ValueError("El repositorio sustituyó el protocolo de incertidumbre.")
        protocol = protocol_record.get("protocol")
        if not isinstance(protocol, dict):
            raise ValueError("El registro carece de protocolo de incertidumbre válido.")

        selected_at = self._aware(confirmation.get("selectedAt"), "selectedAt")
        cutoff = self._aware(confirmation.get("asOf"), "asOf")
        registered_at = self._aware(protocol_record.get("registered_at"), "registered_at")
        if registered_at > selected_at:
            raise ValueError(
                "El protocolo de incertidumbre fue registrado después del freeze de la política."
            )

        requested = self._horizons(confirmation.get("requestedHorizons"))
        required = self._horizons(protocol.get("requiredHorizons"))
        if required != requested:
            raise ValueError("El protocolo de incertidumbre no cubre exactamente los horizontes sellados.")

        selection_fingerprint = self._sha256(
            confirmation.get("selectionFingerprint"), "selectionFingerprint"
        )
        selection_record = self._selection_repository.get(
            selection_fingerprint=selection_fingerprint
        )
        if selection_record is None:
            raise ValueError("La selección congelada de acciones no está registrada.")
        if self._selection_repository.validate_record(selection_record) is not selection_record:
            raise ValueError("El repositorio sustituyó la selección congelada.")
        if self._aware(selection_record.get("selected_at"), "selection.selected_at") != selected_at:
            raise ValueError("selectedAt no coincide con el registro de selección congelado.")
        if self._sha256(
            selection_record.get("registration_fingerprint"),
            "selection.registration_fingerprint",
        ) != self._sha256(
            confirmation.get("selectionRegistrationFingerprint"),
            "selectionRegistrationFingerprint",
        ):
            raise ValueError("La confirmación no pertenece al registro de selección persistido.")
        selection = selection_record.get("selection")
        if not isinstance(selection, dict):
            raise ValueError("La selección congelada carece de payload válido.")

        validated_contract = self._contract_validator.validate(economic_contract)
        if validated_contract is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")
        contract_fingerprint = self._sha256(
            economic_contract.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )
        if contract_fingerprint != self._sha256(
            confirmation.get("economicContractFingerprint"),
            "confirmation.economicContractFingerprint",
        ):
            raise ValueError("El contrato económico no coincide con la confirmación sellada.")
        if contract_fingerprint != self._sha256(
            selection.get("economicContractFingerprint"),
            "selection.economicContractFingerprint",
        ):
            raise ValueError("El contrato económico no coincide con la selección congelada.")

        dataset = self._dataset_service.build(
            as_of=cutoff,
            symbol=symbol,
            horizons=requested,
        )
        self._assert_dataset_shadow(dataset, cutoff=cutoff, requested=requested, symbol=symbol)
        rows = self._eligible_rows(
            dataset=dataset,
            selected_at=selected_at,
            cutoff=cutoff,
            requested=requested,
        )
        sealed_counts = confirmation.get("eligibleSourceRowCounts")
        if not isinstance(sealed_counts, dict):
            raise ValueError("La confirmación carece de conteos sellados.")
        reconstructed_counts = {
            str(horizon): sum(1 for row in rows if row["horizonDays"] == horizon)
            for horizon in requested
        }
        if reconstructed_counts != sealed_counts:
            raise ValueError("La reconstrucción PIT no reproduce los conteos del primer sello.")

        criteria = protocol.get("criteriaByHorizonAndState")
        confirmation_horizons = confirmation.get("horizons")
        selection_horizons = selection.get("selections")
        if not isinstance(criteria, dict):
            raise ValueError("El protocolo carece de criterios de incertidumbre.")
        if not isinstance(confirmation_horizons, dict) or not isinstance(selection_horizons, dict):
            raise ValueError("Faltan horizontes sellados o seleccionados.")

        horizon_results: dict[str, Any] = {}
        all_pass = True
        for horizon in requested:
            key = str(horizon)
            source_rows = [row for row in rows if row["horizonDays"] == horizon]
            sealed_horizon = confirmation_horizons.get(key)
            selected_horizon = selection_horizons.get(key)
            horizon_criteria = criteria.get(key)
            if not isinstance(sealed_horizon, dict) or not isinstance(selected_horizon, dict):
                raise ValueError("Falta un horizonte sellado o congelado.")
            if not isinstance(horizon_criteria, dict):
                raise ValueError("Faltan criterios precomprometidos para un horizonte.")
            if sealed_horizon.get("sourceRowCount") != len(source_rows):
                raise ValueError("sourceRowCount no coincide con la reconstrucción PIT.")
            sealed_states = sealed_horizon.get("states")
            selected_states = selected_horizon.get("states")
            if not isinstance(sealed_states, dict) or set(sealed_states) != set(self.STATES):
                raise ValueError("La confirmación no cubre exactamente todos los estados.")
            if not isinstance(selected_states, dict) or set(selected_states) != set(self.STATES):
                raise ValueError("La selección no cubre exactamente todos los estados.")

            state_results: dict[str, Any] = {}
            horizon_pass = True
            for state in self.STATES:
                sealed_metric = sealed_states.get(state)
                selected_state = selected_states.get(state)
                criterion = horizon_criteria.get(state)
                if not isinstance(sealed_metric, dict) or not isinstance(selected_state, dict):
                    raise ValueError("Falta una métrica o política de estado.")
                if not isinstance(criterion, dict):
                    raise ValueError("Falta un criterio de incertidumbre de estado.")
                policy = selected_state.get("selectedPolicy")
                if not isinstance(policy, dict) or policy.get("currentState") != state:
                    raise ValueError("La política congelada no corresponde al estado.")
                policy_fingerprint = self._sha256(
                    policy.get("policyFingerprint"), "policyFingerprint"
                )
                if policy_fingerprint != self._sha256(
                    sealed_metric.get("selectedPolicyFingerprint"),
                    "selectedPolicyFingerprint",
                ):
                    raise ValueError("La política reconstruida no coincide con el primer sello.")

                increments = self._incremental_utilities(
                    policy=policy,
                    state=state,
                    rows=source_rows,
                    economic_contract=economic_contract,
                )
                count = len(increments)
                if count < 2:
                    raise ValueError("La incertidumbre requiere al menos dos observaciones futuras.")
                if sealed_metric.get("rowCount") != count:
                    raise ValueError("rowCount no coincide con la reconstrucción PIT.")
                mean = sum(increments) / count
                sealed_mean = self._finite(
                    sealed_metric.get("meanIncrementalUtilityVsHold"),
                    "meanIncrementalUtilityVsHold",
                )
                if not math.isclose(mean, sealed_mean, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("La reconstrucción PIT no reproduce la media sellada.")
                sample_variance = sum((value - mean) ** 2 for value in increments) / (count - 1)
                sample_std = math.sqrt(sample_variance)
                standard_error = sample_std / math.sqrt(count)
                self._finite(sample_std, "sampleStdDevIncrementalUtilityVsHold")
                self._finite(standard_error, "standardErrorIncrementalUtilityVsHold")

                multiplier = self._finite(
                    criterion.get("confidenceMultiplier"), "confidenceMultiplier"
                )
                minimum_lower = self._finite(
                    criterion.get("minimumLowerConfidenceBoundIncrementalUtilityVsHold"),
                    "minimumLowerConfidenceBoundIncrementalUtilityVsHold",
                )
                if multiplier <= 0.0 or minimum_lower < 0.0:
                    raise ValueError("El criterio de incertidumbre contiene rangos inválidos.")
                lower_bound = mean - multiplier * standard_error
                self._finite(lower_bound, "lowerConfidenceBoundIncrementalUtilityVsHold")
                passes = lower_bound >= minimum_lower
                horizon_pass = horizon_pass and passes
                state_results[state] = {
                    "passesPrecommittedUncertaintyCriterion": passes,
                    "blockers": [] if passes else ["lower_bound_below_precommitted_minimum"],
                    "rowCount": count,
                    "selectedPolicyFingerprint": policy_fingerprint,
                    "meanIncrementalUtilityVsHold": mean,
                    "sampleStdDevIncrementalUtilityVsHold": sample_std,
                    "standardErrorIncrementalUtilityVsHold": standard_error,
                    "confidenceMultiplier": multiplier,
                    "lowerConfidenceBoundIncrementalUtilityVsHold": lower_bound,
                    "minimumLowerConfidenceBoundIncrementalUtilityVsHold": minimum_lower,
                }
            all_pass = all_pass and horizon_pass
            horizon_results[key] = {
                "horizonDays": horizon,
                "passesPrecommittedUncertaintyCriteria": horizon_pass,
                "sourceRowCount": len(source_rows),
                "states": state_results,
            }

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "protocolId": protocol.get("protocolId"),
            "protocolFingerprint": self._sha256(
                protocol.get("protocolFingerprint"), "protocolFingerprint"
            ),
            "protocolRegisteredAt": registered_at.isoformat(),
            "selectionFingerprint": selection_fingerprint,
            "confirmationFingerprint": self._sha256(
                confirmation.get("confirmationFingerprint"), "confirmationFingerprint"
            ),
            "economicContractFingerprint": contract_fingerprint,
            "selectedAt": selected_at.isoformat(),
            "confirmationAsOf": cutoff.isoformat(),
            "symbolScope": symbol,
            "requiredHorizons": requested,
            "horizons": horizon_results,
            "allRequiredPoliciesPassUncertainty": all_pass,
        }
        return {
            "status": (
                "action_uncertainty_evidence_ready"
                if all_pass
                else "action_uncertainty_evidence_insufficient"
            ),
            **core,
            "actionUncertaintyEvidenceFingerprint": self._fingerprint(core),
            "actionUncertaintyEvidenceReady": all_pass,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "allocation": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "uncertaintyDataSource": "exact_first_seal_pit_window_reconstruction",
                "sealedCountsAndMeansMustReproduceExactly": True,
                "confidenceMultiplierSource": "explicit_precommitted_protocol",
                "codeDefaultConfidenceMultiplier": False,
                "lowerBoundIsProbabilityGuarantee": False,
                "passingEvidenceIsNotProductionAuthorization": True,
                "automaticTrading": False,
            },
        }

    def _incremental_utilities(
        self,
        *,
        policy: dict[str, Any],
        state: str,
        rows: list[dict[str, Any]],
        economic_contract: dict[str, Any],
    ) -> list[float]:
        values: list[float] = []
        for row in rows:
            signal = self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            realized = self._finite(row.get("realizedExcessReturn"), "realizedExcessReturn")
            utility = self._utility_service.evaluate(
                economic_contract=economic_contract,
                current_state=state,
                realized_excess_return=realized,
            )
            self._assert_utility_shadow(utility, state=state, contract=economic_contract)
            action = self._decide(policy, signal)
            allowed = utility.get("allowedActionUtilities")
            if not isinstance(allowed, dict) or action not in allowed or "hold" not in allowed:
                raise ValueError("La política eligió una acción sin utilidad comparable a HOLD.")
            selected = self._net(allowed[action])
            hold = self._net(allowed["hold"])
            values.append(selected - hold)
        return values

    def _validated_confirmation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("confirmation_artifact debe ser un objeto.")
        if payload.get("artifactVersion") != self.CONFIRMATION_VERSION:
            raise ValueError("Versión de confirmación no compatible.")
        if payload.get("status") != "shadow_action_threshold_future_confirmation_sealed":
            raise ValueError("Se exige la primera confirmación futura sellada.")
        if payload.get("futureConfirmationEvaluated") is not True:
            raise ValueError("La confirmación futura todavía no fue evaluada.")
        if payload.get("firstMatureEvaluationSealed") is not True:
            raise ValueError("La primera evaluación madura debe estar sellada.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La confirmación debe mantener advisoryStatus=no_advice.")
        for field in ("productionEligible", "recommendationCandidateReady"):
            if payload.get(field) is not False:
                raise ValueError(f"La confirmación violó {field}=False.")
        if payload.get("action") is not None or payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError("La confirmación shadow no puede contener acción, score ni convicción.")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise ValueError("La confirmación debe mantener automaticTrading=False.")
        core_keys = (
            "artifactVersion",
            "selectionFingerprint",
            "selectionRegistrationFingerprint",
            "economicContractFingerprint",
            "selectedAt",
            "asOf",
            "requestedHorizons",
            "minimumSourceRowsPerHorizon",
            "eligibleSourceRowCounts",
            "horizons",
        )
        core = {key: payload.get(key) for key in core_keys}
        supplied = self._sha256(payload.get("confirmationFingerprint"), "confirmationFingerprint")
        if self._fingerprint(core) != supplied:
            raise ValueError("La confirmación sellada fue modificada.")
        return payload

    def _assert_dataset_shadow(
        self,
        dataset: dict[str, Any],
        *,
        cutoff: datetime,
        requested: list[int],
        symbol: str | None,
    ) -> None:
        if not isinstance(dataset, dict) or dataset.get("datasetVersion") != self.DATASET_VERSION:
            raise ValueError("Dataset de incertidumbre no compatible.")
        if self._aware(dataset.get("asOf"), "dataset.asOf") != cutoff:
            raise ValueError("El dataset cambió el corte PIT.")
        if self._horizons(dataset.get("requestedHorizons")) != requested:
            raise ValueError("El dataset cambió los horizontes solicitados.")
        if dataset.get("symbol") != symbol:
            raise ValueError("El dataset cambió el scope de símbolo solicitado.")
        rows = dataset.get("rows")
        if not isinstance(rows, list) or dataset.get("rowCount") != len(rows):
            raise ValueError("El dataset contiene un conteo de filas inconsistente.")
        core = {
            "datasetVersion": dataset.get("datasetVersion"),
            "asOf": dataset.get("asOf"),
            "symbol": dataset.get("symbol"),
            "requestedHorizons": dataset.get("requestedHorizons"),
            "rowCount": dataset.get("rowCount"),
            "rows": rows,
        }
        if self._fingerprint(core) != self._sha256(
            dataset.get("datasetFingerprint"), "datasetFingerprint"
        ):
            raise ValueError("El dataset de incertidumbre fue modificado.")
        if dataset.get("advisoryStatus") != "no_advice":
            raise ValueError("El dataset debe mantener no_advice.")
        if dataset.get("productionEligible") is not False:
            raise ValueError("El dataset debe mantener productionEligible=False.")
        if dataset.get("recommendationCandidateReady") is not False:
            raise ValueError("El dataset no puede habilitar recomendaciones.")
        dataset_policy = dataset.get("policy")
        if not isinstance(dataset_policy, dict) or dataset_policy.get("automaticTrading") is not False:
            raise ValueError("El dataset debe mantener automaticTrading=False.")

    def _eligible_rows(
        self,
        *,
        dataset: dict[str, Any],
        selected_at: datetime,
        cutoff: datetime,
        requested: list[int],
    ) -> list[dict[str, Any]]:
        raw_rows = dataset.get("rows")
        if not isinstance(raw_rows, list):
            raise ValueError("El dataset carece de rows.")
        seen: set[tuple[int, int]] = set()
        result: list[dict[str, Any]] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                raise ValueError("El dataset contiene una fila inválida.")
            candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            if horizon not in requested:
                raise ValueError("El dataset devolvió un horizonte no solicitado.")
            identity = (candidate_id, horizon)
            if identity in seen:
                raise ValueError("El dataset contiene candidate/horizon duplicado.")
            seen.add(identity)
            candidate_as_of = self._aware(row.get("candidateAsOf"), "candidateAsOf")
            due_at = self._aware(row.get("outcomeDueAt"), "outcomeDueAt")
            evaluated_at = self._aware(row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt")
            self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            self._finite(row.get("realizedExcessReturn"), "realizedExcessReturn")
            if evaluated_at < due_at:
                raise ValueError("Un outcome fue evaluado antes de madurar.")
            if evaluated_at > cutoff:
                raise ValueError("Un outcome posterior al primer sello atravesó la reconstrucción.")
            if candidate_as_of <= selected_at:
                continue
            if due_at <= selected_at or evaluated_at <= selected_at:
                raise ValueError("La reconstrucción contiene evidencia conocida antes del freeze.")
            result.append(row)
        return result

    def _assert_utility_shadow(
        self,
        payload: dict[str, Any],
        *,
        state: str,
        contract: dict[str, Any],
    ) -> None:
        if not isinstance(payload, dict):
            raise ValueError("La utilidad debe ser un objeto.")
        if payload.get("currentState") != state:
            raise ValueError("La utilidad pertenece a otro estado.")
        if self._sha256(
            payload.get("economicContractFingerprint"), "utility.economicContractFingerprint"
        ) != self._sha256(
            contract.get("economicContractFingerprint"), "economicContractFingerprint"
        ):
            raise ValueError("La utilidad pertenece a otro contrato económico.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La utilidad debe mantener no_advice.")
        if payload.get("productionEligible") is not False or payload.get("action") is not None:
            raise ValueError("La utilidad shadow intentó escapar a producción.")
        if payload.get("automaticTrading") is not False:
            raise ValueError("La utilidad debe mantener automaticTrading=False.")

    def _decide(self, policy: dict[str, Any], signal: float) -> str:
        state = str(policy.get("currentState") or "")
        thresholds = policy.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("La política carece de thresholds.")
        if state == "flat":
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            return "buy" if signal >= buy else "hold"
        if state == "reduced_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            if not sell < buy:
                raise ValueError("La política reduced_long exige sell < buy.")
            if signal <= sell:
                return "sell"
            if signal >= buy:
                return "buy"
            return "hold"
        if state == "full_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            reduce = self._finite(thresholds.get("reduceAtOrBelow"), "reduceAtOrBelow")
            if not sell < reduce:
                raise ValueError("La política full_long exige sell < reduce.")
            if signal <= sell:
                return "sell"
            if signal <= reduce:
                return "reduce"
            return "hold"
        raise ValueError("Estado de política no soportado.")

    def _net(self, payload: object) -> float:
        if not isinstance(payload, dict):
            raise ValueError("La utilidad permitida tiene formato inválido.")
        return self._finite(payload.get("netRealizedExcessUtility"), "netRealizedExcessUtility")

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("Los horizontes deben formar una lista no vacía.")
        result: list[int] = []
        for item in value:
            result.append(self._positive_int(item, "horizon"))
        if len(set(result)) != len(result):
            raise ValueError("Los horizontes contienen duplicados.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

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

    def _aware(self, value: object, field: str) -> datetime:
        raw = self._text(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

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
