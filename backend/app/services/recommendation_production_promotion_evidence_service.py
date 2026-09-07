from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_production_promotion_protocol_repository import (
    RecommendationProductionPromotionProtocolRepository,
)


class RecommendationProductionPromotionEvidenceService:
    """Evaluate sealed post-selection evidence against a precommitted protocol.

    This service deliberately has no default production thresholds. Any acceptance
    criteria must arrive in a fingerprinted protocol whose registration timestamp
    is not later than the research cutoff of the evidence being judged. The
    production-facing path additionally loads that protocol from the immutable
    registry, so callers cannot backdate a protocol after seeing confirmation data.
    Passing the protocol only means that production evidence is ready for an
    explicit later promotion decision; it never makes a recommendation, mutates a
    model, allocates capital, or enables trading.
    """

    PROTOCOL_VERSION = "athena-production-promotion-protocol-v1"
    CONFIRMATION_VERSION = "shadow-post-selection-multi-horizon-v1"

    def __init__(
        self,
        protocol_repository: RecommendationProductionPromotionProtocolRepository
        | None = None,
    ) -> None:
        self._protocol_repository = (
            protocol_repository
            if protocol_repository is not None
            else RecommendationProductionPromotionProtocolRepository()
        )

    def evaluate_registered(
        self,
        *,
        confirmation_artifact: dict[str, Any],
        protocol_id: str,
    ) -> dict[str, Any]:
        """Evaluate only against a protocol proven to exist in the registry."""
        normalized_id = self._non_empty_string(protocol_id, "protocol_id")
        record = self._protocol_repository.get(protocol_id=normalized_id)
        if record is None:
            raise ValueError("El protocolo de promoción no está registrado.")
        validated_record = self._protocol_repository.validate_record(record)
        protocol = validated_record.get("protocol")
        if not isinstance(protocol, dict):
            raise ValueError("El registro de protocolo no contiene un protocolo válido.")

        result = self.evaluate(
            confirmation_artifact=confirmation_artifact,
            promotion_protocol=protocol,
        )
        return {
            **result,
            "protocolPersistence": {
                "registered": True,
                "recordId": validated_record.get("id"),
                "createdAt": validated_record.get("created_at"),
                "registeredAt": validated_record.get("registered_at"),
                "protocolFingerprint": validated_record.get("protocol_fingerprint"),
            },
            "policy": {
                **result["policy"],
                "registeredProtocolRequiredForProductionPath": True,
                "callerSuppliedRegistrationTimeAccepted": False,
            },
        }

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

            confirmation_row_count = self._positive_int(
                evidence.get("confirmationRowCount"), "confirmationRowCount"
            )
            non_overlapping_window_count = self._non_negative_int(
                evidence.get("nonOverlappingConfirmationWindowCount"),
                "nonOverlappingConfirmationWindowCount",
            )
            unverifiable_window_count = self._non_negative_int(
                evidence.get("unverifiableConfirmationWindowCount"),
                "unverifiableConfirmationWindowCount",
            )
            issuer_coverage = self._validated_issuer_coverage(
                evidence.get("issuerCoverage"), confirmation_row_count
            )
            relative_mse_improvement = self._finite_float(
                evidence.get("relativeMseImprovement"), "relativeMseImprovement"
            )
            criteria = protocol["criteriaByHorizon"][key]

            if confirmation_row_count < criteria["minimumConfirmationRowCount"]:
                blockers.append("confirmation_sample_below_precommitted_minimum")
            if (
                non_overlapping_window_count
                < criteria["minimumNonOverlappingConfirmationWindowCount"]
            ):
                blockers.append(
                    "confirmation_temporal_breadth_below_precommitted_minimum"
                )
            if unverifiable_window_count > 0:
                blockers.append("confirmation_contains_unverifiable_temporal_windows")
            if (
                issuer_coverage["resolvedIssuerCoverageRatio"]
                < criteria["minimumResolvedIssuerCoverageRatio"]
            ):
                blockers.append("issuer_coverage_below_precommitted_minimum")
            if (
                issuer_coverage["maximumResolvedIssuerConcentrationRatio"]
                > criteria["maximumResolvedIssuerConcentrationRatio"]
            ):
                blockers.append("issuer_concentration_above_precommitted_maximum")
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
                "confirmationRowCount": confirmation_row_count,
                "minimumConfirmationRowCount": criteria["minimumConfirmationRowCount"],
                "nonOverlappingConfirmationWindowCount": non_overlapping_window_count,
                "minimumNonOverlappingConfirmationWindowCount": criteria[
                    "minimumNonOverlappingConfirmationWindowCount"
                ],
                "unverifiableConfirmationWindowCount": unverifiable_window_count,
                "issuerCoverage": issuer_coverage,
                "minimumResolvedIssuerCoverageRatio": criteria[
                    "minimumResolvedIssuerCoverageRatio"
                ],
                "maximumResolvedIssuerConcentrationRatio": criteria[
                    "maximumResolvedIssuerConcentrationRatio"
                ],
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
                "minimumConfirmationSampleMustBePrecommitted": True,
                "minimumTemporalBreadthMustBePrecommitted": True,
                "unverifiableTemporalWindowsBlockPromotionEvidence": True,
                "nonOverlappingWindowsDoNotClaimStatisticalIndependence": True,
                "issuerCoverageMustBePrecommitted": True,
                "issuerConcentrationMustBePrecommitted": True,
                "issuerDiversityDoesNotClaimStatisticalIndependence": True,
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
            minimum_row_count = self._positive_int(
                item.get("minimumConfirmationRowCount"),
                "minimumConfirmationRowCount",
            )
            minimum_non_overlapping_window_count = self._positive_int(
                item.get("minimumNonOverlappingConfirmationWindowCount"),
                "minimumNonOverlappingConfirmationWindowCount",
            )
            if minimum_non_overlapping_window_count > minimum_row_count:
                raise ValueError(
                    "minimumNonOverlappingConfirmationWindowCount no puede superar "
                    "minimumConfirmationRowCount."
                )
            minimum_issuer_coverage = self._bounded_float(
                item.get("minimumResolvedIssuerCoverageRatio"),
                "minimumResolvedIssuerCoverageRatio",
                0.0,
                1.0,
            )
            maximum_issuer_concentration = self._bounded_float(
                item.get("maximumResolvedIssuerConcentrationRatio"),
                "maximumResolvedIssuerConcentrationRatio",
                0.0,
                1.0,
            )
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
                "minimumConfirmationRowCount": minimum_row_count,
                "minimumNonOverlappingConfirmationWindowCount": (
                    minimum_non_overlapping_window_count
                ),
                "minimumResolvedIssuerCoverageRatio": minimum_issuer_coverage,
                "maximumResolvedIssuerConcentrationRatio": maximum_issuer_concentration,
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

    def _validated_issuer_coverage(
        self, payload: object, confirmation_row_count: int
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("issuerCoverage es obligatorio en evidencia de confirmación.")
        row_count = self._positive_int(payload.get("rowCount"), "issuerCoverage.rowCount")
        resolved = self._non_negative_int(
            payload.get("resolvedIssuerRowCount"),
            "issuerCoverage.resolvedIssuerRowCount",
        )
        unresolved = self._non_negative_int(
            payload.get("unresolvedIssuerRowCount"),
            "issuerCoverage.unresolvedIssuerRowCount",
        )
        distinct = self._non_negative_int(
            payload.get("distinctResolvedIssuerCount"),
            "issuerCoverage.distinctResolvedIssuerCount",
        )
        maximum_rows = self._non_negative_int(
            payload.get("maximumRowsPerResolvedIssuer"),
            "issuerCoverage.maximumRowsPerResolvedIssuer",
        )
        coverage = self._bounded_float(
            payload.get("resolvedIssuerCoverageRatio"),
            "issuerCoverage.resolvedIssuerCoverageRatio",
            0.0,
            1.0,
        )
        concentration = self._bounded_float(
            payload.get("maximumResolvedIssuerConcentrationRatio"),
            "issuerCoverage.maximumResolvedIssuerConcentrationRatio",
            0.0,
            1.0,
        )
        if row_count != confirmation_row_count:
            raise ValueError("issuerCoverage.rowCount no coincide con confirmationRowCount.")
        if resolved + unresolved != row_count:
            raise ValueError("issuerCoverage no reconcilia filas resueltas y no resueltas.")
        if distinct > resolved or maximum_rows > resolved:
            raise ValueError("issuerCoverage contiene conteos canónicos inconsistentes.")
        expected_coverage = resolved / row_count
        expected_concentration = maximum_rows / resolved if resolved else 1.0
        if not math.isclose(coverage, expected_coverage, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("issuerCoverage.resolvedIssuerCoverageRatio es inconsistente.")
        if not math.isclose(
            concentration,
            expected_concentration,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "issuerCoverage.maximumResolvedIssuerConcentrationRatio es inconsistente."
            )
        if payload.get("statisticalIndependence") != "not_claimed":
            raise ValueError("issuerCoverage no puede afirmar independencia estadística.")
        if payload.get("thresholdsApplied") is not False:
            raise ValueError("issuerCoverage no puede aplicar thresholds retrospectivos.")
        return {
            "rowCount": row_count,
            "resolvedIssuerRowCount": resolved,
            "unresolvedIssuerRowCount": unresolved,
            "resolvedIssuerCoverageRatio": coverage,
            "distinctResolvedIssuerCount": distinct,
            "maximumRowsPerResolvedIssuer": maximum_rows,
            "maximumResolvedIssuerConcentrationRatio": concentration,
            "statisticalIndependence": "not_claimed",
            "thresholdsApplied": False,
        }

    def _non_empty_string(self, value: object, field: str) -> str:
        parsed = str(value or "").strip()
        if not parsed:
            raise ValueError(f"{field} es obligatorio.")
        return parsed

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser un entero positivo.")
        return value

    def _non_negative_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} debe ser un entero no negativo.")
        return value

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
