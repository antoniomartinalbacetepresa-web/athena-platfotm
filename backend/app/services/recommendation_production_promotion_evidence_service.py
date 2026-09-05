from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any


class RecommendationProductionPromotionEvidenceService:
    """Evaluate sealed post-selection evidence against a precommitted protocol.

    This service deliberately has no default production thresholds. Any acceptance
    criteria must arrive in a fingerprinted protocol whose registration timestamp
    is not later than the research cutoff of the evidence being judged. Passing the
    protocol only means that production evidence is ready for an explicit later
    promotion decision; it never makes a recommendation, mutates a model, allocates
    capital, or enables trading.
    """

    PROTOCOL_VERSION = "athena-production-promotion-protocol-v1"
    CONFIRMATION_VERSION = "shadow-post-selection-multi-horizon-v1"

    def evaluate(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        promotion_protocol: dict[str, Any],
    ) -> dict[str, Any]:
        confirmation = self._validated_confirmation(confirmation_artifact)
        protocol = self._validated_protocol(promotion_protocol)

        research_cutoff = self._parse_utc(
            confirmation.get("researchCutoff"), "researchCutoff"
        )
        registered_at = self._parse_utc(protocol.get("registeredAt"), "registeredAt")
        if registered_at > research_cutoff:
            raise ValueError(
                "El protocolo de promoción debe quedar registrado antes o en el researchCutoff."
            )

        gate_fingerprint = self._non_empty_string(
            confirmation.get("researchGateFingerprint"), "researchGateFingerprint"
        )
        if protocol["researchGateFingerprint"] != gate_fingerprint:
            raise ValueError(
                "El protocolo de promoción pertenece a otra research gate."
            )

        evidence_horizons = confirmation.get("horizons")
        if not isinstance(evidence_horizons, dict):
            raise ValueError("La evidencia debe incluir horizons.")

        horizon_results: dict[str, dict[str, Any]] = {}
        all_pass = True
        for horizon in protocol["requiredHorizons"]:
            key = str(horizon)
            evidence = evidence_horizons.get(key)
            if not isinstance(evidence, dict):
                horizon_results[key] = {
                    "horizonDays": horizon,
                    "passesPrecommittedCriteria": False,
                    "blockers": ["required_horizon_missing"],
                }
                all_pass = False
                continue

            blockers: list[str] = []
            if evidence.get("confirmed") is not True:
                blockers.append("post_selection_confirmation_not_ready")

            metrics = evidence.get("metrics")
            if not isinstance(metrics, dict):
                blockers.append("confirmation_metrics_missing")
                sign_accuracy = None
            else:
                sign_accuracy = self._finite_float(
                    metrics.get("signAccuracy"), "signAccuracy"
                )

            relative_mse_improvement = self._finite_float(
                evidence.get("relativeMseImprovement"), "relativeMseImprovement"
            )
            criteria = protocol["criteriaByHorizon"][key]

            if sign_accuracy is not None and sign_accuracy < criteria["minimumSignAccuracy"]:
                blockers.append("sign_accuracy_below_precommitted_minimum")
            if relative_mse_improvement < criteria["minimumRelativeMseImprovement"]:
                blockers.append("relative_mse_improvement_below_precommitted_minimum")
            if (
                criteria["requireBeatZeroExcessMseBaseline"]
                and evidence.get("beatsZeroBaselineOnMse") is not True
            ):
                blockers.append("zero_excess_mse_baseline_not_beaten")

            passes = not blockers
            all_pass = all_pass and passes
            horizon_results[key] = {
                "horizonDays": horizon,
                "passesPrecommittedCriteria": passes,
                "blockers": blockers,
                "modelFingerprint": evidence.get("modelFingerprint"),
                "selectionFingerprint": evidence.get("selectionFingerprint"),
                "confirmationStart": evidence.get("confirmationStart"),
                "confirmationRowCount": evidence.get("confirmationRowCount"),
                "signAccuracy": sign_accuracy,
                "relativeMseImprovement": relative_mse_improvement,
                "beatsZeroBaselineOnMse": evidence.get("beatsZeroBaselineOnMse"),
            }

        evidence_ready = bool(protocol["requiredHorizons"]) and all_pass
        return {
            "status": (
                "production_promotion_evidence_ready"
                if evidence_ready
                else "production_promotion_evidence_not_ready"
            ),
            "protocolId": protocol["protocolId"],
            "protocolFingerprint": protocol["protocolFingerprint"],
            "registeredAt": protocol["registeredAt"],
            "researchGateFingerprint": gate_fingerprint,
            "researchCutoff": confirmation["researchCutoff"],
            "confirmationEvidenceFingerprint": confirmation[
                "confirmationEvidenceFingerprint"
            ],
            "requiredHorizons": list(protocol["requiredHorizons"]),
            "horizons": horizon_results,
            "productionPromotionEvidenceReady": evidence_ready,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "criteriaSource": "explicit_precommitted_protocol_no_code_defaults",
                "registrationMustPrecedeOrEqualResearchCutoff": True,
                "sameResearchGateRequired": True,
                "sealedConfirmationFingerprintRequired": True,
                "confirmationEvidenceCanRetuneCriteria": False,
                "passingEvidenceIsNotProductionAuthorization": True,
            },
        }

    def fingerprint_protocol(self, protocol_without_fingerprint: dict[str, Any]) -> str:
        core = self._protocol_core(protocol_without_fingerprint)
        return self._fingerprint(core)

    def _validated_protocol(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("promotion_protocol debe ser un objeto.")
        core = self._protocol_core(payload)
        supplied = self._non_empty_string(
            payload.get("protocolFingerprint"), "protocolFingerprint"
        )
        expected = self._fingerprint(core)
        if supplied != expected:
            raise ValueError("El protocolo de promoción fue modificado o no está sellado.")
        return {**core, "protocolFingerprint": supplied}

    def _protocol_core(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("artifactVersion") != self.PROTOCOL_VERSION:
            raise ValueError("Versión de protocolo de promoción no compatible.")
        protocol_id = self._non_empty_string(payload.get("protocolId"), "protocolId")
        registered_at = self._parse_utc(payload.get("registeredAt"), "registeredAt")
        research_gate = self._non_empty_string(
            payload.get("researchGateFingerprint"), "researchGateFingerprint"
        )
        required = payload.get("requiredHorizons")
        if not isinstance(required, list) or not required:
            raise ValueError("requiredHorizons debe ser una lista no vacía.")
        horizons: list[int] = []
        for value in required:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("requiredHorizons sólo admite enteros positivos.")
            horizons.append(value)
        if len(set(horizons)) != len(horizons):
            raise ValueError("requiredHorizons no puede contener duplicados.")

        criteria_payload = payload.get("criteriaByHorizon")
        if not isinstance(criteria_payload, dict):
            raise ValueError("criteriaByHorizon es obligatorio.")
        criteria: dict[str, dict[str, Any]] = {}
        for horizon in horizons:
            key = str(horizon)
            item = criteria_payload.get(key)
            if not isinstance(item, dict):
                raise ValueError(f"Faltan criterios precomprometidos para {horizon} días.")
            sign_accuracy = self._bounded_float(
                item.get("minimumSignAccuracy"),
                "minimumSignAccuracy",
                0.0,
                1.0,
            )
            minimum_improvement = self._finite_float(
                item.get("minimumRelativeMseImprovement"),
                "minimumRelativeMseImprovement",
            )
            beat_baseline = item.get("requireBeatZeroExcessMseBaseline")
            if not isinstance(beat_baseline, bool):
                raise ValueError("requireBeatZeroExcessMseBaseline debe ser booleano.")
            criteria[key] = {
                "minimumSignAccuracy": sign_accuracy,
                "minimumRelativeMseImprovement": minimum_improvement,
                "requireBeatZeroExcessMseBaseline": beat_baseline,
            }

        return {
            "artifactVersion": self.PROTOCOL_VERSION,
            "protocolId": protocol_id,
            "registeredAt": registered_at.isoformat(),
            "researchGateFingerprint": research_gate,
            "requiredHorizons": horizons,
            "criteriaByHorizon": criteria,
        }

    def _validated_confirmation(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("confirmation_artifact debe ser un objeto.")
        if payload.get("artifactVersion") != self.CONFIRMATION_VERSION:
            raise ValueError("Versión de evidencia de confirmación no compatible.")
        if payload.get("productionEligible") is not False:
            raise ValueError("La confirmación violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("La confirmación violó advisoryStatus=no_advice.")

        fingerprint = self._non_empty_string(
            payload.get("confirmationEvidenceFingerprint"),
            "confirmationEvidenceFingerprint",
        )
        core_keys = (
            "artifactVersion",
            "researchGateFingerprint",
            "researchCutoff",
            "asOf",
            "requestedHorizons",
            "confirmedHorizonCount",
            "passingHorizonCount",
            "confirmationPassRatio",
            "postSelectionProtocolEvidenceReady",
            "horizons",
            "thresholds",
        )
        core = {key: payload.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("La evidencia de confirmación fue modificada.")
        self._parse_utc(core.get("researchCutoff"), "researchCutoff")
        self._parse_utc(core.get("asOf"), "asOf")
        return dict(payload)

    def _non_empty_string(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _finite_float(self, value: object, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{field} debe ser finito.")
        return parsed

    def _bounded_float(
        self, value: object, field: str, minimum: float, maximum: float
    ) -> float:
        parsed = self._finite_float(value, field)
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"{field} debe estar entre {minimum} y {maximum}.")
        return parsed

    def _parse_utc(self, value: object, field: str) -> datetime:
        raw = self._non_empty_string(value, field)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        try:
            serialized = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("El artefacto contiene valores no serializables o no finitos.") from exc
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
