from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_shadow_action_threshold_confirmation_repository import (
    RecommendationShadowActionThresholdConfirmationRepository,
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


class _SelectionRepository(Protocol):
    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _ConfirmationRepository(Protocol):
    def get(self, *, selection_fingerprint: str) -> dict[str, Any] | None: ...

    def seal(
        self,
        *,
        selection_fingerprint: str,
        confirmation: dict[str, Any],
        sealed_at: datetime,
    ) -> dict[str, Any]: ...

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


class RecommendationShadowActionThresholdFutureConfirmationService:
    """Evaluate frozen threshold policies on genuinely post-selection live evidence.

    Readiness calls expose only counts. Performance is computed exactly once when
    every requested horizon has a fixed, pre-specified minimum number of post-freeze
    source rows. That first mature evaluation is sealed, preventing optional stopping
    by repeatedly checking the same threshold selection until results improve.
    """

    ARTIFACT_VERSION = "shadow-action-threshold-future-confirmation-v1"
    STATES = ("flat", "reduced_long", "full_long")
    MIN_SOURCE_ROWS_PER_HORIZON = 20

    def __init__(
        self,
        *,
        selection_repository: _SelectionRepository | None = None,
        confirmation_repository: _ConfirmationRepository | None = None,
        dataset_service: _DatasetService | None = None,
        contract_validator: _ContractValidator | None = None,
        utility_service: _UtilityService | None = None,
    ) -> None:
        self._selection_repository = (
            selection_repository
            or RecommendationShadowActionThresholdSelectionRepository()
        )
        self._confirmation_repository = (
            confirmation_repository
            or RecommendationShadowActionThresholdConfirmationRepository()
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

    def evaluate(
        self,
        *,
        selection_fingerprint: str,
        economic_contract: dict[str, Any],
        as_of: datetime,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        fingerprint = self._sha256(selection_fingerprint, "selection_fingerprint")
        cutoff = self._aware_utc(as_of, "as_of")

        selection_record = self._selection_repository.get(
            selection_fingerprint=fingerprint
        )
        if selection_record is None:
            raise ValueError("La selección de thresholds no fue congelada previamente.")
        if self._selection_repository.validate_record(selection_record) is not selection_record:
            raise ValueError("El repositorio sustituyó el registro de selección.")
        selection = selection_record.get("selection")
        if not isinstance(selection, dict):
            raise ValueError("El registro de selección carece de artefacto válido.")
        self._assert_selection_shadow(selection, fingerprint)
        selected_at = self._parse_aware(
            selection_record.get("selected_at"), "selected_at"
        )
        if cutoff <= selected_at:
            raise ValueError("as_of debe ser posterior al freeze de thresholds.")

        validated_contract = self._contract_validator.validate(economic_contract)
        if validated_contract is not economic_contract:
            raise ValueError("El validador sustituyó el contrato económico.")
        contract_fingerprint = self._sha256(
            economic_contract.get("economicContractFingerprint"),
            "economicContractFingerprint",
        )
        if contract_fingerprint != selection.get("economicContractFingerprint"):
            raise ValueError("El contrato económico no coincide con la selección congelada.")

        existing = self._confirmation_repository.get(
            selection_fingerprint=fingerprint
        )
        if existing is not None:
            if self._confirmation_repository.validate_record(existing) is not existing:
                raise ValueError("El repositorio sustituyó la confirmación sellada.")
            confirmation = existing.get("confirmation")
            if not isinstance(confirmation, dict):
                raise ValueError("La confirmación sellada carece de artefacto válido.")
            self._assert_confirmation_shadow(confirmation, fingerprint)
            return confirmation

        requested = self._horizons(selection.get("requestedHorizons"))
        dataset = self._dataset_service.build(
            as_of=cutoff,
            symbol=symbol,
            horizons=requested,
        )
        self._assert_dataset_shadow(dataset, cutoff, requested)
        eligible_rows = self._eligible_future_rows(
            dataset=dataset,
            selected_at=selected_at,
            cutoff=cutoff,
            requested=requested,
        )
        counts = {
            str(horizon): sum(
                1 for row in eligible_rows if row["horizonDays"] == horizon
            )
            for horizon in requested
        }
        all_mature = all(
            count >= self.MIN_SOURCE_ROWS_PER_HORIZON for count in counts.values()
        )
        if not all_mature:
            return {
                "status": "shadow_action_threshold_future_confirmation_pending",
                "artifactVersion": self.ARTIFACT_VERSION,
                "selectionFingerprint": fingerprint,
                "selectedAt": selected_at.isoformat(),
                "asOf": cutoff.isoformat(),
                "requestedHorizons": requested,
                "minimumSourceRowsPerHorizon": self.MIN_SOURCE_ROWS_PER_HORIZON,
                "eligibleSourceRowCounts": counts,
                "performanceMetricsExposed": False,
                "futureConfirmationEvaluated": False,
                "firstMatureEvaluationSealed": False,
                "futureConfirmationPassed": None,
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "recommendationCandidateReady": False,
                "actionThresholdCalibrationResearchEligible": False,
                "actionThresholds": None,
                "action": None,
                "score": None,
                "conviction": None,
                "policy": self._pending_policy(),
            }

        metrics = self._evaluate_fixed_policies(
            selection=selection,
            economic_contract=economic_contract,
            rows=eligible_rows,
            requested=requested,
        )
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "selectionFingerprint": fingerprint,
            "selectionRegistrationFingerprint": self._sha256(
                selection_record.get("registration_fingerprint"),
                "selectionRegistrationFingerprint",
            ),
            "economicContractFingerprint": contract_fingerprint,
            "selectedAt": selected_at.isoformat(),
            "asOf": cutoff.isoformat(),
            "requestedHorizons": requested,
            "minimumSourceRowsPerHorizon": self.MIN_SOURCE_ROWS_PER_HORIZON,
            "eligibleSourceRowCounts": counts,
            "horizons": metrics,
        }
        confirmation = {
            "status": "shadow_action_threshold_future_confirmation_sealed",
            **core,
            "confirmationFingerprint": self._fingerprint(core),
            "performanceMetricsExposed": True,
            "futureConfirmationEvaluated": True,
            "firstMatureEvaluationSealed": True,
            "futureConfirmationPassed": None,
            "formalStatisticalPromotionGateImplemented": False,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "actionThresholds": None,
            "action": None,
            "score": None,
            "conviction": None,
            "policy": self._sealed_policy(),
        }
        sealed = self._confirmation_repository.seal(
            selection_fingerprint=fingerprint,
            confirmation=confirmation,
            sealed_at=cutoff,
        )
        if self._confirmation_repository.validate_record(sealed) is not sealed:
            raise ValueError("El repositorio sustituyó la confirmación al sellarla.")
        persisted = sealed.get("confirmation")
        if not isinstance(persisted, dict):
            raise ValueError("El sello persistido carece de confirmación válida.")
        self._assert_confirmation_shadow(persisted, fingerprint)
        return persisted

    def _evaluate_fixed_policies(
        self,
        *,
        selection: dict[str, Any],
        economic_contract: dict[str, Any],
        rows: list[dict[str, Any]],
        requested: list[int],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        selections = selection.get("selections")
        if not isinstance(selections, dict):
            raise ValueError("La selección congelada carece de horizontes.")
        for horizon in requested:
            source_rows = [row for row in rows if row["horizonDays"] == horizon]
            horizon_selection = selections.get(str(horizon))
            if not isinstance(horizon_selection, dict):
                raise ValueError("Falta la política congelada de un horizonte.")
            states = horizon_selection.get("states")
            if not isinstance(states, dict):
                raise ValueError("Faltan estados congelados para un horizonte.")
            state_metrics: dict[str, Any] = {}
            for state in self.STATES:
                payload = states.get(state)
                if not isinstance(payload, dict):
                    raise ValueError("Falta una selección congelada de estado.")
                policy = payload.get("selectedPolicy")
                if not isinstance(policy, dict) or policy.get("currentState") != state:
                    raise ValueError("La política congelada no corresponde a su estado.")
                selected_values: list[float] = []
                hold_values: list[float] = []
                regrets: list[float] = []
                action_counts: dict[str, int] = defaultdict(int)
                for row in source_rows:
                    signal = self._finite(
                        row.get("expectedExcessReturn"), "expectedExcessReturn"
                    )
                    realized = self._finite(
                        row.get("realizedExcessReturn"), "realizedExcessReturn"
                    )
                    utility = self._utility_service.evaluate(
                        economic_contract=economic_contract,
                        current_state=state,
                        realized_excess_return=realized,
                    )
                    self._assert_utility_shadow(utility, state, contract=economic_contract)
                    action = self._decide(policy, signal)
                    allowed = utility.get("allowedActionUtilities")
                    if not isinstance(allowed, dict) or action not in allowed or "hold" not in allowed:
                        raise ValueError("La política congelada eligió una acción no permitida.")
                    selected = self._net(allowed[action])
                    hold = self._net(allowed["hold"])
                    best = max(self._net(item) for item in allowed.values())
                    selected_values.append(selected)
                    hold_values.append(hold)
                    regrets.append(best - selected)
                    action_counts[action] += 1
                count = len(source_rows)
                state_metrics[state] = {
                    "rowCount": count,
                    "selectedPolicyFingerprint": self._sha256(
                        policy.get("policyFingerprint"), "policyFingerprint"
                    ),
                    "meanNetRealizedExcessUtility": sum(selected_values) / count,
                    "meanHoldNetRealizedExcessUtility": sum(hold_values) / count,
                    "meanIncrementalUtilityVsHold": (
                        sum(selected_values) - sum(hold_values)
                    )
                    / count,
                    "meanHindsightRegret": sum(regrets) / count,
                    "nonHoldDecisionRate": (
                        sum(value for action, value in action_counts.items() if action != "hold")
                        / count
                    ),
                    "actionCounts": dict(sorted(action_counts.items())),
                }
            result[str(horizon)] = {
                "horizonDays": horizon,
                "sourceRowCount": len(source_rows),
                "states": state_metrics,
            }
        return result

    def _eligible_future_rows(
        self,
        *,
        dataset: dict[str, Any],
        selected_at: datetime,
        cutoff: datetime,
        requested: list[int],
    ) -> list[dict[str, Any]]:
        raw_rows = dataset.get("rows")
        if not isinstance(raw_rows, list):
            raise ValueError("El dataset de confirmación carece de rows.")
        seen: set[tuple[int, int]] = set()
        eligible: list[dict[str, Any]] = []
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
            candidate_as_of = self._parse_aware(row.get("candidateAsOf"), "candidateAsOf")
            due_at = self._parse_aware(row.get("outcomeDueAt"), "outcomeDueAt")
            evaluated_at = self._parse_aware(
                row.get("outcomeEvaluatedAt"), "outcomeEvaluatedAt"
            )
            if evaluated_at < due_at:
                raise ValueError("Un outcome fue evaluado antes de madurar.")
            if evaluated_at > cutoff:
                raise ValueError("Un outcome posterior a as_of atravesó la confirmación.")
            self._finite(row.get("expectedExcessReturn"), "expectedExcessReturn")
            self._finite(row.get("realizedExcessReturn"), "realizedExcessReturn")
            if candidate_as_of <= selected_at:
                continue
            if due_at <= selected_at or evaluated_at <= selected_at:
                raise ValueError("Evidencia post-freeze contiene un outcome conocido demasiado pronto.")
            eligible.append(row)
        return eligible

    def _assert_dataset_shadow(
        self,
        dataset: dict[str, Any],
        cutoff: datetime,
        requested: list[int],
    ) -> None:
        if not isinstance(dataset, dict):
            raise ValueError("El dataset de confirmación debe ser un objeto.")
        if dataset.get("datasetVersion") != "shadow-action-calibration-v2":
            raise ValueError("Versión de dataset de confirmación no soportada.")
        if self._parse_aware(dataset.get("asOf"), "dataset.asOf") != cutoff:
            raise ValueError("El dataset cambió el corte as_of.")
        if self._horizons(dataset.get("requestedHorizons")) != requested:
            raise ValueError("El dataset cambió los horizontes solicitados.")
        rows = dataset.get("rows")
        if not isinstance(rows, list) or dataset.get("rowCount") != len(rows):
            raise ValueError("El contador de filas del dataset es inconsistente.")
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
            raise ValueError("El fingerprint del dataset de confirmación no coincide.")
        if dataset.get("advisoryStatus") != "no_advice":
            raise ValueError("El dataset abandonó no_advice.")
        for field in (
            "productionEligible",
            "recommendationCandidateReady",
            "actionThresholdCalibrationResearchEligible",
        ):
            if dataset.get(field) is not False:
                raise ValueError(f"El dataset intentó habilitar {field}.")
        for field in ("actionThresholds", "action", "score", "conviction"):
            if dataset.get(field) is not None:
                raise ValueError(f"El dataset no puede publicar {field}.")
        policy = dataset.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El dataset carece de policy.")
        if policy.get("evidenceSource") != "trusted_persisted_live_cycle_attestation_v1_only":
            raise ValueError("El dataset no procede exclusivamente de ciclos live atestados.")
        if policy.get("researchHoldoutReuse") is not False:
            raise ValueError("El dataset reutilizó evidencia research/holdout.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError("El dataset habilitó promoción automática.")
        if policy.get("automaticTrading") is not False:
            raise ValueError("El dataset habilitó trading automático.")

    def _assert_selection_shadow(
        self, selection: dict[str, Any], fingerprint: str
    ) -> None:
        if selection.get("selectionFingerprint") != fingerprint:
            raise ValueError("El registro cambió el fingerprint de selección.")
        if selection.get("status") != "shadow_action_threshold_selection_frozen_for_future_confirmation":
            raise ValueError("La selección no está congelada para confirmación.")
        if selection.get("futureReserveConfirmationEligible") is not True:
            raise ValueError("La selección no es elegible para confirmación futura.")
        if selection.get("advisoryStatus") != "no_advice":
            raise ValueError("La selección abandonó no_advice.")
        if selection.get("productionEligible") is not False:
            raise ValueError("La selección intentó habilitar producción.")
        if selection.get("recommendationCandidateReady") is not False:
            raise ValueError("La selección intentó habilitar recomendación.")
        policy = selection.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("La selección carece de policy.")
        if policy.get("futureReserveConsumed") is not False:
            raise ValueError("La selección ya consumió reserva futura.")
        if policy.get("selectedResearchThresholdsMayBeRefitOnFutureReserve") is not False:
            raise ValueError("La selección permite refit con evidencia futura.")

    def _assert_confirmation_shadow(
        self, confirmation: dict[str, Any], fingerprint: str
    ) -> None:
        if confirmation.get("status") != "shadow_action_threshold_future_confirmation_sealed":
            raise ValueError("El sello no contiene una confirmación válida.")
        if confirmation.get("selectionFingerprint") != fingerprint:
            raise ValueError("El sello pertenece a otra selección.")
        if confirmation.get("advisoryStatus") != "no_advice":
            raise ValueError("La confirmación abandonó no_advice.")
        if confirmation.get("productionEligible") is not False:
            raise ValueError("La confirmación intentó habilitar producción.")
        if confirmation.get("recommendationCandidateReady") is not False:
            raise ValueError("La confirmación intentó habilitar recomendación.")
        if confirmation.get("futureConfirmationPassed") is not None:
            raise ValueError("La confirmación no puede autoaprobarse sin gate estadística.")
        if confirmation.get("formalStatisticalPromotionGateImplemented") is not False:
            raise ValueError("La confirmación fingió disponer de gate estadística.")
        if confirmation.get("action") is not None:
            raise ValueError("La confirmación no puede publicar una acción.")

    def _assert_utility_shadow(
        self,
        utility: dict[str, Any],
        state: str,
        *,
        contract: dict[str, Any],
    ) -> None:
        if not isinstance(utility, dict) or utility.get("currentState") != state:
            raise ValueError("La utilidad económica devolvió otro estado.")
        if utility.get("economicContractFingerprint") != contract.get(
            "economicContractFingerprint"
        ):
            raise ValueError("La utilidad económica cambió el contrato.")
        if utility.get("advisoryStatus") != "no_advice":
            raise ValueError("La utilidad económica abandonó no_advice.")
        if utility.get("productionEligible") is not False:
            raise ValueError("La utilidad económica intentó habilitar producción.")
        if utility.get("action") is not None or utility.get("automaticTrading") is not False:
            raise ValueError("La utilidad económica intentó actuar automáticamente.")

    def _decide(self, policy: dict[str, Any], signal: float) -> str:
        state = str(policy.get("currentState") or "")
        thresholds = policy.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError("La política congelada carece de thresholds.")
        if state == "flat":
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            return "buy" if signal >= buy else "hold"
        if state == "reduced_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            buy = self._finite(thresholds.get("buyAtOrAbove"), "buyAtOrAbove")
            if not sell < buy:
                raise ValueError("La política reduced_long no mantiene sell < buy.")
            if signal <= sell:
                return "sell"
            if signal >= buy:
                return "buy"
            return "hold"
        if state == "full_long":
            sell = self._finite(thresholds.get("sellAtOrBelow"), "sellAtOrBelow")
            reduce = self._finite(thresholds.get("reduceAtOrBelow"), "reduceAtOrBelow")
            if not sell < reduce:
                raise ValueError("La política full_long no mantiene sell < reduce.")
            if signal <= sell:
                return "sell"
            if signal <= reduce:
                return "reduce"
            return "hold"
        raise ValueError("Estado de política congelada no soportado.")

    def _pending_policy(self) -> dict[str, Any]:
        return {
            "futureEvidenceBoundary": "candidate_as_of_strictly_after_immutable_selected_at",
            "readinessBeforeMinimum": "counts_only_no_performance_metrics",
            "minimumSourceRowsPerHorizon": self.MIN_SOURCE_ROWS_PER_HORIZON,
            "futureReserveConsumed": False,
            "thresholdRefitAllowed": False,
            "policyReselectionAllowed": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _sealed_policy(self) -> dict[str, Any]:
        return {
            "futureEvidenceBoundary": "candidate_as_of_strictly_after_immutable_selected_at",
            "firstMatureEvaluation": "sqlite_immutable_seal",
            "minimumSourceRowsPerHorizon": self.MIN_SOURCE_ROWS_PER_HORIZON,
            "futureReserveConsumed": True,
            "thresholdRefitAllowed": False,
            "policyReselectionAllowed": False,
            "formalStatisticalPromotionGate": "not_yet_implemented_fail_closed",
            "automaticProductionPromotion": False,
            "automaticTrading": False,
        }

    def _net(self, payload: object) -> float:
        if not isinstance(payload, dict):
            raise ValueError("La utilidad de acción tiene formato inválido.")
        return self._finite(
            payload.get("netRealizedExcessUtility"),
            "netRealizedExcessUtility",
        )

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requestedHorizons debe ser una lista no vacía.")
        result: list[int] = []
        seen: set[int] = set()
        for raw in value:
            horizon = self._positive_int(raw, "requestedHorizons")
            if horizon in seen:
                raise ValueError("requestedHorizons contiene duplicados.")
            seen.add(horizon)
            result.append(horizon)
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

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _sha256(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return normalized

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
