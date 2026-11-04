from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_action_calibration_utility_panel_service import (
    RecommendationShadowActionCalibrationUtilityPanelService,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class _CandidateRepository(Protocol):
    def get(self, candidate_id: int) -> dict[str, Any] | None: ...


class RecommendationActionModelIdentityAttestationService:
    """Prove an action-policy selection used one exact model revision per horizon.

    The historical action-calibration panel intentionally stores decision features,
    not model identity. This service reconstructs that missing identity from the
    immutable persisted live candidates and fails closed if train/validation rows
    mix model revisions within the same horizon.
    """

    ARTIFACT_VERSION = "athena-action-model-identity-attestation-v1"
    SELECTION_VERSION = "shadow-action-threshold-selection-v1"

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        candidate_validator: RecommendationShadowLiveCandidateService | None = None,
        panel_validator: RecommendationShadowActionCalibrationUtilityPanelService | None = None,
    ) -> None:
        self._candidate_repository = candidate_repository or RecommendationShadowLiveCandidateRepository()
        self._candidate_validator = candidate_validator or RecommendationShadowLiveCandidateService()
        self._panel_validator = panel_validator or RecommendationShadowActionCalibrationUtilityPanelService()

    def attest(
        self,
        *,
        utility_panel: dict[str, Any],
        selection: dict[str, Any],
    ) -> dict[str, Any]:
        panel = self._panel_validator.validate_artifact(utility_panel)
        if panel is not utility_panel:
            raise ValueError("El validador sustituyó el panel de utilidad.")
        selection = self._validated_selection(selection, panel)

        identities: dict[tuple[int, int], dict[str, Any]] = {}
        model_sets: dict[int, set[str]] = {}
        source_rows = list(panel.get("trainUtilityRows") or []) + list(
            panel.get("validationUtilityRows") or []
        )
        if not source_rows:
            raise ValueError("El panel no contiene evidencia train/validation.")

        for row in source_rows:
            if not isinstance(row, dict):
                raise ValueError("El panel contiene una fila inválida.")
            candidate_id = self._positive_int(row.get("candidateId"), "candidateId")
            horizon = self._positive_int(row.get("horizonDays"), "horizonDays")
            identity = (candidate_id, horizon)
            stored = identities.get(identity)
            if stored is None:
                persisted = self._candidate_repository.get(candidate_id)
                if persisted is None:
                    raise ValueError("Falta un candidato persistido usado por la calibración de acciones.")
                artifact = persisted.get("artifact")
                if not isinstance(artifact, dict):
                    raise ValueError("El candidato persistido carece de artifact.")
                if self._candidate_validator.validate_artifact(artifact) is not artifact:
                    raise ValueError("El validador sustituyó el candidato persistido.")
                if self._sha256(
                    persisted.get("candidate_fingerprint"), "candidate_fingerprint"
                ) != self._sha256(artifact.get("candidateFingerprint"), "candidateFingerprint"):
                    raise ValueError("El repositorio y el artifact discrepan en candidateFingerprint.")
                horizons = artifact.get("horizons")
                if not isinstance(horizons, dict):
                    raise ValueError("El candidato persistido carece de horizons.")
                live = horizons.get(str(horizon))
                if not isinstance(live, dict):
                    raise ValueError("El candidato persistido carece del horizonte calibrado.")
                if self._positive_int(live.get("horizonDays"), "live.horizonDays") != horizon:
                    raise ValueError("La identidad del horizonte persistido es inconsistente.")
                expected = self._finite(live.get("expectedExcessReturn"), "live.expectedExcessReturn")
                row_expected = self._finite(row.get("expectedExcessReturn"), "row.expectedExcessReturn")
                if expected != row_expected:
                    raise ValueError("La señal de calibración no coincide con el candidato persistido.")
                if str(artifact.get("symbol") or "").strip().upper() != str(row.get("symbol") or "").strip().upper():
                    raise ValueError("La fila de calibración cambió el símbolo del candidato.")
                if str(artifact.get("asOf") or "") != str(row.get("candidateAsOf") or ""):
                    raise ValueError("La fila de calibración cambió candidateAsOf.")
                model_fingerprint = self._sha256(
                    live.get("modelFingerprint"), f"modelFingerprint.{horizon}"
                )
                stored = {
                    "candidateId": candidate_id,
                    "horizonDays": horizon,
                    "candidateFingerprint": self._sha256(
                        artifact.get("candidateFingerprint"), "candidateFingerprint"
                    ),
                    "modelFingerprint": model_fingerprint,
                }
                identities[identity] = stored
                model_sets.setdefault(horizon, set()).add(model_fingerprint)

        requested = self._horizons(selection.get("requestedHorizons"))
        model_map: dict[str, str] = {}
        for horizon in requested:
            models = model_sets.get(horizon, set())
            if not models:
                raise ValueError("No existe identidad de modelo para un horizonte seleccionado.")
            if len(models) != 1:
                raise ValueError(
                    "La calibración de acciones mezcla revisiones de modelo dentro de un horizonte."
                )
            model_map[str(horizon)] = next(iter(models))

        unique_rows = [identities[key] for key in sorted(identities)]
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "selectionFingerprint": self._sha256(
                selection.get("selectionFingerprint"), "selectionFingerprint"
            ),
            "utilityPanelFingerprint": self._sha256(
                panel.get("utilityPanelFingerprint"), "utilityPanelFingerprint"
            ),
            "economicContractFingerprint": self._sha256(
                panel.get("economicContractFingerprint"), "economicContractFingerprint"
            ),
            "requestedHorizons": requested,
            "modelFingerprintsByHorizon": model_map,
            "uniqueCandidateHorizonCount": len(unique_rows),
            "candidateHorizonIdentities": unique_rows,
        }
        return {
            "status": "action_calibration_model_identity_attested",
            **core,
            "modelIdentityAttestationFingerprint": self._fingerprint(core),
            "singleModelRevisionPerHorizon": True,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
            "automaticProductionPromotion": False,
            "automaticTrading": False,
            "policy": {
                "identitySource": "immutable_persisted_live_candidate_artifacts",
                "mixedModelRevisionsAllowedWithinHorizon": False,
                "callerSuppliedModelFingerprintTrusted": False,
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de atestación de identidad de modelo no compatible.")
        self._assert_shadow(artifact)
        if artifact.get("status") != "action_calibration_model_identity_attested":
            raise ValueError("La atestación no está disponible.")
        if artifact.get("singleModelRevisionPerHorizon") is not True:
            raise ValueError("La atestación no garantiza una única revisión por horizonte.")
        requested = self._horizons(artifact.get("requestedHorizons"))
        model_map = artifact.get("modelFingerprintsByHorizon")
        if not isinstance(model_map, dict) or set(model_map) != {str(x) for x in requested}:
            raise ValueError("modelFingerprintsByHorizon no cubre los horizontes requeridos.")
        normalized_models = {
            str(horizon): self._sha256(
                model_map[str(horizon)], f"modelFingerprintsByHorizon.{horizon}"
            )
            for horizon in requested
        }
        identities = artifact.get("candidateHorizonIdentities")
        if not isinstance(identities, list) or not identities:
            raise ValueError("La atestación carece de identidades fuente.")
        if artifact.get("uniqueCandidateHorizonCount") != len(identities):
            raise ValueError("uniqueCandidateHorizonCount es inconsistente.")
        seen: set[tuple[int, int]] = set()
        for item in identities:
            if not isinstance(item, dict):
                raise ValueError("Una identidad fuente es inválida.")
            candidate_id = self._positive_int(item.get("candidateId"), "candidateId")
            horizon = self._positive_int(item.get("horizonDays"), "horizonDays")
            identity = (candidate_id, horizon)
            if identity in seen:
                raise ValueError("La atestación contiene candidate/horizon duplicado.")
            seen.add(identity)
            model = self._sha256(item.get("modelFingerprint"), "modelFingerprint")
            if normalized_models.get(str(horizon)) != model:
                raise ValueError("Una identidad fuente no coincide con el modelo atestado.")
            self._sha256(item.get("candidateFingerprint"), "candidateFingerprint")
        core_keys = (
            "artifactVersion",
            "selectionFingerprint",
            "utilityPanelFingerprint",
            "economicContractFingerprint",
            "requestedHorizons",
            "modelFingerprintsByHorizon",
            "uniqueCandidateHorizonCount",
            "candidateHorizonIdentities",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(
            artifact.get("modelIdentityAttestationFingerprint"),
            "modelIdentityAttestationFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La atestación de identidad fue modificada.")
        return artifact

    def _validated_selection(
        self, selection: dict[str, Any], panel: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(selection, dict) or selection.get("artifactVersion") != self.SELECTION_VERSION:
            raise ValueError("Versión de selección de thresholds no compatible.")
        self._assert_shadow(selection)
        if selection.get("status") != "shadow_action_threshold_selection_frozen_for_future_confirmation":
            raise ValueError("La selección de thresholds no está completa.")
        if selection.get("futureReserveConfirmationEligible") is not True:
            raise ValueError("La selección no está preparada para confirmación futura.")
        if selection.get("sourceUtilityPanelFingerprint") != panel.get("utilityPanelFingerprint"):
            raise ValueError("La selección no pertenece al panel de utilidad suministrado.")
        if selection.get("economicContractFingerprint") != panel.get("economicContractFingerprint"):
            raise ValueError("La selección cambió el contrato económico.")
        if self._horizons(selection.get("requestedHorizons")) != self._horizons(
            panel.get("requestedHorizons")
        ):
            raise ValueError("La selección cambió los horizontes del panel.")
        core_keys = (
            "artifactVersion",
            "sourceUtilityPanelFingerprint",
            "candidateSetFingerprint",
            "economicContractFingerprint",
            "requestedHorizons",
            "minimumValidationRowsPerState",
            "allRequestedHorizonsAndStatesSelected",
            "selections",
        )
        core = {key: selection.get(key) for key in core_keys}
        supplied = self._sha256(selection.get("selectionFingerprint"), "selectionFingerprint")
        if self._fingerprint(core) != supplied:
            raise ValueError("La selección de thresholds fue modificada.")
        return selection

    def _assert_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El artefacto debe mantener advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El artefacto debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El artefacto no puede habilitar recomendaciones.")
        if payload.get("action") is not None:
            raise ValueError("El artefacto no puede contener action.")
        if payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError("El artefacto no puede publicar score/conviction.")

    def _horizons(self, value: object) -> list[int]:
        if not isinstance(value, list) or not value:
            raise ValueError("requestedHorizons debe ser una lista no vacía.")
        result: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError("requestedHorizons sólo admite enteros positivos.")
            result.append(item)
        if len(set(result)) != len(result):
            raise ValueError("requestedHorizons no admite duplicados.")
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
