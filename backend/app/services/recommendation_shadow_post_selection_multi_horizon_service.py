from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.services.recommendation_shadow_gated_freeze_service import (
    RecommendationShadowGatedFreezeService,
)
from app.services.recommendation_shadow_post_selection_pipeline_service import (
    RecommendationShadowPostSelectionPipelineService,
)


class RecommendationShadowPostSelectionMultiHorizonService:
    """Aggregate post-selection confirmation without mixing research lineages.

    Each candidate must be a cryptographically valid gated-freeze bundle from the
    same research gate and research cutoff. Confirmation is then evaluated using
    the immutable persisted selection boundary for each frozen model. The result
    is a research-only evidence artifact: it can document whether a protocol has
    survived genuinely later data, but it cannot assign actions, calibrate action
    thresholds on that evidence, or promote anything to production.
    """

    ARTIFACT_VERSION = "shadow-post-selection-multi-horizon-v1"
    DEFAULT_HORIZONS = (7, 30, 90, 180, 365)

    def __init__(
        self,
        *,
        gated_freeze_service: RecommendationShadowGatedFreezeService | None = None,
        post_selection_pipeline: RecommendationShadowPostSelectionPipelineService | None = None,
        minimum_confirmed_horizons: int = 3,
        minimum_pass_ratio: float = 2.0 / 3.0,
        minimum_sign_accuracy: float = 0.50,
    ) -> None:
        if minimum_confirmed_horizons <= 0:
            raise ValueError("minimum_confirmed_horizons debe ser positivo.")
        if not (0.0 < minimum_pass_ratio <= 1.0):
            raise ValueError("minimum_pass_ratio debe estar en (0, 1].")
        if not (0.0 <= minimum_sign_accuracy <= 1.0):
            raise ValueError("minimum_sign_accuracy debe estar en [0, 1].")
        self._gated_freeze_service = (
            gated_freeze_service or RecommendationShadowGatedFreezeService()
        )
        self._post_selection_pipeline = (
            post_selection_pipeline or RecommendationShadowPostSelectionPipelineService()
        )
        self._minimum_confirmed_horizons = int(minimum_confirmed_horizons)
        self._minimum_pass_ratio = float(minimum_pass_ratio)
        self._minimum_sign_accuracy = float(minimum_sign_accuracy)

    def evaluate(
        self,
        *,
        gated_bundles: list[dict[str, Any]],
        as_of: datetime,
        horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    ) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        requested_horizons = self._validated_horizons(horizons)
        bundles = self._validated_bundles(gated_bundles)

        if not bundles:
            return self._empty_result(cutoff, requested_horizons)

        gate_fingerprints = {bundle["researchGateFingerprint"] for bundle in bundles}
        research_cutoffs = {bundle["researchCutoff"] for bundle in bundles}
        if len(gate_fingerprints) != 1 or len(research_cutoffs) != 1:
            raise ValueError(
                "Todos los candidatos de confirmación deben proceder de la misma research gate y researchCutoff."
            )

        research_gate_fingerprint = next(iter(gate_fingerprints))
        research_cutoff = next(iter(research_cutoffs))
        by_horizon: dict[int, dict[str, Any]] = {}
        for bundle in bundles:
            horizon = int(bundle["horizonDays"])
            if horizon in by_horizon:
                raise ValueError("No puede haber dos candidatos para el mismo horizonte.")
            by_horizon[horizon] = bundle

        horizon_results: dict[str, dict[str, Any]] = {}
        confirmed_count = 0
        passing_count = 0
        for horizon in requested_horizons:
            bundle = by_horizon.get(horizon)
            if bundle is None:
                horizon_results[str(horizon)] = {
                    "horizonDays": horizon,
                    "status": "candidate_missing",
                    "confirmed": False,
                    "passesConfirmationProtocol": False,
                    "reason": "No existe candidato gated-freeze para este horizonte.",
                }
                continue

            frozen_model = bundle["frozenModel"]
            result = self._post_selection_pipeline.evaluate_registered_selection(
                model_fingerprint=str(frozen_model["fingerprint"]),
                as_of=cutoff,
            )
            self._assert_shadow(result, f"post_selection_{horizon}")
            reported_horizon = result.get("horizonDays")
            if reported_horizon is not None and int(reported_horizon) != horizon:
                raise ValueError("La confirmación cambió el horizonte del candidato.")
            if result.get("modelFingerprint") not in (None, frozen_model["fingerprint"]):
                raise ValueError("La confirmación devolvió otro modelo congelado.")

            confirmed = result.get("postSelectionConfirmationEvidenceReady") is True
            passes = False
            reasons: list[str] = []
            if confirmed:
                confirmed_count += 1
                metrics = result.get("metrics")
                if not isinstance(metrics, dict):
                    raise ValueError("Una confirmación madura debe incluir métricas.")
                sign_accuracy = self._finite_float(metrics.get("signAccuracy"), "signAccuracy")
                improvement = self._finite_float(
                    result.get("relativeMseImprovement"), "relativeMseImprovement"
                )
                beats_baseline = result.get("beatsZeroBaselineOnMse") is True
                if not beats_baseline:
                    reasons.append("does_not_beat_zero_excess_mse_baseline")
                if improvement <= 0.0:
                    reasons.append("non_positive_relative_mse_improvement")
                if sign_accuracy < self._minimum_sign_accuracy:
                    reasons.append("sign_accuracy_below_protocol_floor")
                passes = not reasons
                if passes:
                    passing_count += 1
            else:
                reasons.append(str(result.get("status") or "confirmation_not_ready"))

            horizon_results[str(horizon)] = {
                "horizonDays": horizon,
                "status": result.get("status"),
                "confirmed": confirmed,
                "passesConfirmationProtocol": passes,
                "reasons": reasons,
                "modelFingerprint": frozen_model["fingerprint"],
                "bundleFingerprint": bundle["bundleFingerprint"],
                "selectionFingerprint": result.get("selectionFingerprint"),
                "confirmationStart": result.get("confirmationStart"),
                "confirmationRowCount": result.get("confirmationRowCount", 0),
                "metrics": result.get("metrics"),
                "zeroExcessReturnBaseline": result.get("zeroExcessReturnBaseline"),
                "relativeMseImprovement": result.get("relativeMseImprovement"),
                "beatsZeroBaselineOnMse": result.get("beatsZeroBaselineOnMse"),
            }

        pass_ratio = (
            passing_count / confirmed_count if confirmed_count > 0 else 0.0
        )
        protocol_ready = (
            confirmed_count >= self._minimum_confirmed_horizons
            and passing_count >= self._minimum_confirmed_horizons
            and pass_ratio >= self._minimum_pass_ratio
        )

        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "researchGateFingerprint": research_gate_fingerprint,
            "researchCutoff": research_cutoff,
            "asOf": cutoff.isoformat(),
            "requestedHorizons": list(requested_horizons),
            "confirmedHorizonCount": confirmed_count,
            "passingHorizonCount": passing_count,
            "confirmationPassRatio": pass_ratio,
            "postSelectionProtocolEvidenceReady": protocol_ready,
            "horizons": horizon_results,
            "thresholds": {
                "minimumConfirmedHorizons": self._minimum_confirmed_horizons,
                "minimumPassRatio": self._minimum_pass_ratio,
                "minimumSignAccuracy": self._minimum_sign_accuracy,
                "relativeMseImprovement": "strictly_positive",
                "beatsZeroExcessMseBaseline": True,
            },
        }
        fingerprint = self._fingerprint(core)
        return {
            "status": (
                "shadow_post_selection_multi_horizon_confirmed"
                if protocol_ready
                else "shadow_post_selection_multi_horizon_not_confirmed"
            ),
            **core,
            "confirmationEvidenceFingerprint": fingerprint,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        self._assert_shadow(artifact, "multi_horizon_confirmation")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de confirmación multi-horizonte no compatible.")
        fingerprint = artifact.get("confirmationEvidenceFingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("La confirmación multi-horizonte requiere fingerprint.")
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
        core = {key: artifact.get(key) for key in core_keys}
        if self._fingerprint(core) != fingerprint:
            raise ValueError("La evidencia de confirmación multi-horizonte fue modificada.")
        self._validated_horizons(core["requestedHorizons"])
        self._aware_utc(self._parse_datetime(core["asOf"], "asOf"), "asOf")
        self._aware_utc(
            self._parse_datetime(core["researchCutoff"], "researchCutoff"),
            "researchCutoff",
        )
        return artifact

    def _validated_bundles(
        self, bundles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not isinstance(bundles, list):
            raise ValueError("gated_bundles debe ser una lista.")
        result = []
        for bundle in bundles:
            if not isinstance(bundle, dict):
                raise ValueError("Cada gated bundle debe ser un objeto.")
            validated = self._gated_freeze_service.validate_bundle(bundle)
            self._assert_shadow(validated, "gated_bundle")
            result.append(validated)
        return result

    def _validated_horizons(
        self, horizons: tuple[int, ...] | list[int] | object
    ) -> tuple[int, ...]:
        if not isinstance(horizons, (tuple, list)) or not horizons:
            raise ValueError("horizons debe contener al menos un horizonte.")
        values: list[int] = []
        for raw in horizons:
            if isinstance(raw, bool):
                raise ValueError("Los horizontes deben ser enteros positivos.")
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Los horizontes deben ser enteros positivos.") from exc
            if value <= 0 or value != raw:
                raise ValueError("Los horizontes deben ser enteros positivos.")
            values.append(value)
        if len(set(values)) != len(values):
            raise ValueError("Los horizontes no pueden repetirse.")
        return tuple(values)

    def _empty_result(
        self, cutoff: datetime, requested_horizons: tuple[int, ...]
    ) -> dict[str, Any]:
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "researchGateFingerprint": None,
            "researchCutoff": None,
            "asOf": cutoff.isoformat(),
            "requestedHorizons": list(requested_horizons),
            "confirmedHorizonCount": 0,
            "passingHorizonCount": 0,
            "confirmationPassRatio": 0.0,
            "postSelectionProtocolEvidenceReady": False,
            "horizons": {
                str(horizon): {
                    "horizonDays": horizon,
                    "status": "candidate_missing",
                    "confirmed": False,
                    "passesConfirmationProtocol": False,
                    "reason": "No se proporcionaron candidatos gated-freeze.",
                }
                for horizon in requested_horizons
            },
            "thresholds": {
                "minimumConfirmedHorizons": self._minimum_confirmed_horizons,
                "minimumPassRatio": self._minimum_pass_ratio,
                "minimumSignAccuracy": self._minimum_sign_accuracy,
                "relativeMseImprovement": "strictly_positive",
                "beatsZeroExcessMseBaseline": True,
            },
        }
        return {
            "status": "shadow_post_selection_multi_horizon_not_confirmed",
            **core,
            "confirmationEvidenceFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "policy": self._policy(),
        }

    def _policy(self) -> dict[str, Any]:
        return {
            "sameResearchGateRequired": True,
            "sameResearchCutoffRequired": True,
            "uniqueModelPerHorizon": True,
            "selectionBoundary": "immutable_persisted_per_frozen_model",
            "confirmationEvidence": "strictly_post_selection_and_mature",
            "protocolThresholds": "provisional_research_safeguards_not_investment_thresholds",
            "confirmationDataCanFitActionThresholds": False,
            "actions": "not_assigned",
            "automaticModelMutation": False,
            "automaticProductionPromotion": False,
        }

    def _assert_shadow(self, payload: dict[str, Any], stage: str) -> None:
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{stage} violó productionEligible=False.")
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{stage} violó advisoryStatus=no_advice.")

    def _finite_float(self, value: object, field: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(parsed):
            raise ValueError(f"{field} debe ser finito.")
        return parsed

    def _parse_datetime(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
