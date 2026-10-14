from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_action_promotion_protocol_repository import (
    RecommendationActionPromotionProtocolRepository,
)


class RecommendationActionPromotionEvidenceService:
    """Evaluate first-sealed future action-policy evidence against a registered protocol.

    A passing result is research evidence only. It does not emit an action, score,
    allocation or production authorization and cannot execute any transaction.
    """

    ARTIFACT_VERSION = "athena-action-promotion-evidence-v2"
    CONFIRMATION_VERSION = "shadow-action-threshold-future-confirmation-v1"
    STATES = ("flat", "reduced_long", "full_long")

    def __init__(
        self,
        repository: RecommendationActionPromotionProtocolRepository | None = None,
    ) -> None:
        self._repository = repository or RecommendationActionPromotionProtocolRepository()

    def evaluate_registered(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
    ) -> dict[str, Any]:
        record = self._repository.get(protocol_id=self._non_empty(protocol_id, "protocol_id"))
        if record is None:
            raise ValueError("El protocolo de promoción de acciones no está registrado.")
        if self._repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó el protocolo registrado.")
        protocol = record.get("protocol")
        if not isinstance(protocol, dict):
            raise ValueError("El registro carece de protocolo válido.")
        confirmation = self._validated_confirmation(confirmation_artifact)

        registered_at = self._aware(record.get("registered_at"), "registered_at")
        selected_at = self._aware(confirmation.get("selectedAt"), "selectedAt")
        if registered_at > selected_at:
            raise ValueError(
                "El protocolo fue registrado después del freeze de la política; no es precomprometido."
            )

        required_horizons = self._horizons(protocol.get("requiredHorizons"))
        confirmation_horizons = self._horizons(confirmation.get("requestedHorizons"))
        if required_horizons != confirmation_horizons:
            raise ValueError("El protocolo y la confirmación no cubren los mismos horizontes.")

        criteria = protocol.get("criteriaByHorizonAndState")
        minimum_rows = protocol.get("minimumFutureRowsByHorizon")
        metrics_by_horizon = confirmation.get("horizons")
        if not isinstance(criteria, dict) or not isinstance(minimum_rows, dict):
            raise ValueError("Faltan criterios o suficiencia muestral precomprometida.")
        if not isinstance(metrics_by_horizon, dict):
            raise ValueError("Faltan métricas por horizonte.")

        horizon_results: dict[str, Any] = {}
        all_pass = True
        for horizon in required_horizons:
            key = str(horizon)
            horizon_metrics = metrics_by_horizon.get(key)
            horizon_criteria = criteria.get(key)
            if not isinstance(horizon_metrics, dict) or not isinstance(horizon_criteria, dict):
                raise ValueError("Falta un horizonte requerido.")
            if horizon_metrics.get("horizonDays") != horizon:
                raise ValueError("horizonDays no coincide con su clave.")
            minimum_future_rows = self._positive_int(
                minimum_rows.get(key), f"minimumFutureRowsByHorizon.{key}"
            )
            source_row_count = self._positive_int(
                horizon_metrics.get("sourceRowCount"), "sourceRowCount"
            )
            states = horizon_metrics.get("states")
            if not isinstance(states, dict) or set(states) != set(self.STATES):
                raise ValueError("La confirmación debe cubrir exactamente todos los estados.")

            horizon_blockers: list[str] = []
            if source_row_count < minimum_future_rows:
                horizon_blockers.append("future_sample_below_precommitted_minimum")
            state_results: dict[str, Any] = {}
            horizon_pass = not horizon_blockers
            for state in self.STATES:
                metric = states.get(state)
                criterion = horizon_criteria.get(state)
                if not isinstance(metric, dict) or not isinstance(criterion, dict):
                    raise ValueError("Faltan métricas o criterios de un estado.")
                row_count = self._positive_int(metric.get("rowCount"), "rowCount")
                if row_count != source_row_count:
                    raise ValueError("El conteo de filas del estado no coincide con el horizonte.")
                policy_fingerprint = self._sha256(
                    metric.get("selectedPolicyFingerprint"),
                    f"selectedPolicyFingerprint.{key}.{state}",
                )
                incremental = self._finite(
                    metric.get("meanIncrementalUtilityVsHold"),
                    "meanIncrementalUtilityVsHold",
                )
                regret = self._finite(metric.get("meanHindsightRegret"), "meanHindsightRegret")
                non_hold = self._finite(metric.get("nonHoldDecisionRate"), "nonHoldDecisionRate")
                if regret < 0.0 or non_hold < 0.0 or non_hold > 1.0:
                    raise ValueError("Las métricas de política contienen rangos imposibles.")
                minimum_incremental = self._finite(
                    criterion.get("minimumMeanIncrementalUtilityVsHold"),
                    "minimumMeanIncrementalUtilityVsHold",
                )
                maximum_regret = self._finite(
                    criterion.get("maximumMeanHindsightRegret"),
                    "maximumMeanHindsightRegret",
                )
                if maximum_regret < 0.0:
                    raise ValueError("maximumMeanHindsightRegret no puede ser negativo.")
                blockers: list[str] = []
                if source_row_count < minimum_future_rows:
                    blockers.append("future_sample_below_precommitted_minimum")
                if incremental < minimum_incremental:
                    blockers.append("incremental_utility_below_precommitted_minimum")
                if regret > maximum_regret:
                    blockers.append("hindsight_regret_above_precommitted_maximum")
                passes = not blockers
                horizon_pass = horizon_pass and passes
                state_results[state] = {
                    "passesPrecommittedCriteria": passes,
                    "blockers": blockers,
                    "rowCount": row_count,
                    "selectedPolicyFingerprint": policy_fingerprint,
                    "meanIncrementalUtilityVsHold": incremental,
                    "meanHindsightRegret": regret,
                    "nonHoldDecisionRate": non_hold,
                    "minimumMeanIncrementalUtilityVsHold": minimum_incremental,
                    "maximumMeanHindsightRegret": maximum_regret,
                }
            all_pass = all_pass and horizon_pass
            horizon_results[key] = {
                "horizonDays": horizon,
                "passesPrecommittedCriteria": horizon_pass,
                "blockers": horizon_blockers,
                "sourceRowCount": source_row_count,
                "minimumFutureRowsRequired": minimum_future_rows,
                "states": state_results,
            }

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "protocolId": protocol["protocolId"],
            "protocolFingerprint": self._sha256(
                protocol.get("protocolFingerprint"), "protocolFingerprint"
            ),
            "protocolRegisteredAt": registered_at.isoformat(),
            "selectionFingerprint": self._sha256(
                confirmation.get("selectionFingerprint"), "selectionFingerprint"
            ),
            "confirmationFingerprint": self._sha256(
                confirmation.get("confirmationFingerprint"), "confirmationFingerprint"
            ),
            "selectedAt": selected_at.isoformat(),
            "confirmationAsOf": self._aware(confirmation.get("asOf"), "asOf").isoformat(),
            "requiredHorizons": required_horizons,
            "horizons": horizon_results,
            "allRequiredPoliciesPass": all_pass,
        }
        return {
            "status": (
                "action_promotion_evidence_ready"
                if all_pass
                else "action_promotion_evidence_insufficient"
            ),
            **core,
            "actionPromotionEvidenceFingerprint": self._fingerprint(core),
            "actionPromotionEvidenceReady": all_pass,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "allocation": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "registeredProtocolRequired": True,
                "protocolMustPrecedePolicyFreeze": True,
                "firstSealedFutureReserveRequired": True,
                "precommittedProductionSampleSizeRequired": True,
                "researchMaturityCountIsNotProductionSufficiency": True,
                "codeDefaultPromotionThresholds": False,
                "codeDefaultProductionSampleSize": False,
                "passingEvidenceIsNotProductionAuthorization": True,
                "portfolioStateStillRequiredForReduceOrSell": True,
                "automaticTrading": False,
            },
        }

    def _validated_confirmation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("confirmation_artifact debe ser un objeto.")
        if payload.get("artifactVersion") != self.CONFIRMATION_VERSION:
            raise ValueError("Versión de confirmación de acciones no compatible.")
        if payload.get("status") != "shadow_action_threshold_future_confirmation_sealed":
            raise ValueError("Se exige la primera confirmación futura sellada.")
        if payload.get("futureConfirmationEvaluated") is not True:
            raise ValueError("La confirmación futura todavía no fue evaluada.")
        if payload.get("firstMatureEvaluationSealed") is not True:
            raise ValueError("La primera evaluación madura debe estar sellada.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La confirmación violó advisoryStatus=no_advice.")
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
        self._aware(payload.get("selectedAt"), "selectedAt")
        self._aware(payload.get("asOf"), "asOf")
        self._horizons(payload.get("requestedHorizons"))
        return payload

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("Los horizontes deben formar una lista no vacía.")
        result: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError("Los horizontes deben ser enteros positivos.")
            result.append(item)
        if len(set(result)) != len(result):
            raise ValueError("Los horizontes no pueden contener duplicados.")
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

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result

    def _non_empty(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _aware(self, value: object, field: str) -> datetime:
        raw = self._non_empty(value, field)
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
            raise ValueError("El artefacto contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
