from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_live_uncertainty_repository import (
    RecommendationShadowLiveUncertaintyRepository,
)
from app.repositories.recommendation_shadow_repository import RecommendationShadowRepository
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class _CandidateRepository(Protocol):
    def get(self, candidate_id: int) -> dict[str, Any] | None: ...


class _UncertaintyRepository(Protocol):
    def get_for_candidate(self, candidate_id: int) -> dict[str, Any] | None: ...


class _SnapshotRepository(Protocol):
    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None: ...


class _CandidateService(Protocol):
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationShadowLiveAuditService:
    """Read the immutable evidence that existed for a live-shadow prediction.

    This service never reconstructs missing uncertainty from newer data. Legacy
    candidates created before uncertainty sealing are explicitly incomplete, so
    the audit view cannot rewrite history while appearing to improve provenance.
    """

    def __init__(
        self,
        *,
        candidate_repository: _CandidateRepository | None = None,
        uncertainty_repository: _UncertaintyRepository | None = None,
        snapshot_repository: _SnapshotRepository | None = None,
        candidate_service: _CandidateService | None = None,
    ) -> None:
        self._candidate_repository = (
            candidate_repository or RecommendationShadowLiveCandidateRepository()
        )
        self._uncertainty_repository = (
            uncertainty_repository or RecommendationShadowLiveUncertaintyRepository()
        )
        self._snapshot_repository = snapshot_repository or RecommendationShadowRepository()
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()

    def get(self, *, candidate_id: int) -> dict[str, Any]:
        if isinstance(candidate_id, bool) or candidate_id <= 0:
            raise ValueError("candidate_id debe ser positivo.")
        stored = self._candidate_repository.get(candidate_id)
        if stored is None:
            raise ValueError("El candidato shadow live no existe.")
        artifact = stored.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("El candidato persistido carece de artefacto válido.")
        candidate = self._candidate_service.validate_artifact(artifact)
        self._assert_candidate_shadow(candidate)
        candidate_fingerprint = self._sha256(
            candidate.get("candidateFingerprint"), "candidateFingerprint"
        )
        stored_fingerprint = self._sha256(
            stored.get("candidate_fingerprint"), "stored.candidate_fingerprint"
        )
        if candidate_fingerprint != stored_fingerprint:
            raise ValueError("El fingerprint persistido no coincide con el candidato auditado.")

        snapshot_id = self._positive_int(stored.get("snapshot_id"), "snapshot_id")
        snapshot = self._snapshot_repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError("El snapshot PIT del candidato auditado no existe.")
        self._assert_snapshot_binding(snapshot=snapshot, candidate=candidate)

        uncertainty_row = self._uncertainty_repository.get_for_candidate(candidate_id)
        uncertainty: dict[str, Any] | None = None
        uncertainty_id: int | None = None
        uncertainty_fingerprint: str | None = None
        evidence_status = "candidate_and_uncertainty_immutably_available"
        if uncertainty_row is None:
            evidence_status = "legacy_candidate_uncertainty_not_sealed"
        else:
            uncertainty_id = self._positive_int(
                uncertainty_row.get("id"), "uncertainty.id"
            )
            uncertainty_fingerprint = self._sha256(
                uncertainty_row.get("uncertainty_fingerprint"),
                "uncertainty_fingerprint",
            )
            uncertainty_candidate_fingerprint = self._sha256(
                uncertainty_row.get("candidate_fingerprint"),
                "uncertainty.candidate_fingerprint",
            )
            if uncertainty_candidate_fingerprint != candidate_fingerprint:
                raise ValueError("La incertidumbre sellada pertenece a otro candidato.")
            raw_uncertainty = uncertainty_row.get("artifact")
            if not isinstance(raw_uncertainty, dict):
                raise ValueError("La incertidumbre sellada carece de artefacto válido.")
            uncertainty = raw_uncertainty
            self._assert_uncertainty_binding(
                uncertainty=uncertainty,
                candidate_id=candidate_id,
                candidate=candidate,
                candidate_fingerprint=candidate_fingerprint,
            )

        return {
            "status": "shadow_live_audit_available",
            "evidenceStatus": evidence_status,
            "candidateId": candidate_id,
            "candidateFingerprint": candidate_fingerprint,
            "snapshotId": snapshot_id,
            "uncertaintyId": uncertainty_id,
            "uncertaintyFingerprint": uncertainty_fingerprint,
            "symbol": candidate.get("symbol"),
            "asOf": candidate.get("asOf"),
            "candidate": candidate,
            "uncertainty": uncertainty,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "actionThresholdCalibrationResearchEligible": False,
            "action": None,
            "policy": {
                "source": "persisted_immutable_artifacts_only",
                "missingHistoricalUncertainty": "reported_missing_never_recomputed",
                "snapshotBinding": "same_instrument_symbol_and_pit_cutoff_required",
                "candidateIntegrity": "artifact_revalidated_and_sha256_identity_checked",
                "uncertaintyIntegrity": "repository_sha256_seal_verified_on_read",
                "automaticProductionPromotion": False,
                "automaticTrading": False,
            },
        }

    def _assert_candidate_shadow(self, payload: dict[str, Any]) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato auditado debe mantener no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError("El candidato auditado debe mantener productionEligible=False.")
        if payload.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato auditado no puede habilitar recomendaciones.")
        if payload.get("action") is not None:
            raise ValueError("El candidato auditado no puede contener action.")
        if payload.get("score") is not None or payload.get("conviction") is not None:
            raise ValueError("El candidato auditado no puede contener score o conviction.")

    def _assert_snapshot_binding(
        self,
        *,
        snapshot: dict[str, Any],
        candidate: dict[str, Any],
    ) -> None:
        snapshot_symbol = self._required_text(snapshot.get("symbol"), "snapshot.symbol").upper()
        candidate_symbol = self._required_text(candidate.get("symbol"), "candidate.symbol").upper()
        if snapshot_symbol != candidate_symbol:
            raise ValueError("El snapshot PIT auditado pertenece a otro símbolo.")
        snapshot_instrument = self._positive_int(
            snapshot.get("instrument_id"), "snapshot.instrument_id"
        )
        candidate_instrument = self._positive_int(
            candidate.get("instrumentId"), "candidate.instrumentId"
        )
        if snapshot_instrument != candidate_instrument:
            raise ValueError("El snapshot PIT auditado pertenece a otro instrumento.")
        snapshot_cutoff = self._aware(
            snapshot.get("data_cutoff_at"), "snapshot.data_cutoff_at"
        )
        candidate_cutoff = self._aware(candidate.get("asOf"), "candidate.asOf")
        if snapshot_cutoff != candidate_cutoff:
            raise ValueError("El snapshot PIT auditado tiene otro instante de corte.")

    def _assert_uncertainty_binding(
        self,
        *,
        uncertainty: dict[str, Any],
        candidate_id: int,
        candidate: dict[str, Any],
        candidate_fingerprint: str,
    ) -> None:
        if uncertainty.get("artifactVersion") != "shadow-live-uncertainty-v1":
            raise ValueError("La incertidumbre auditada usa una versión desconocida.")
        if self._positive_int(uncertainty.get("candidateId"), "uncertainty.candidateId") != candidate_id:
            raise ValueError("La incertidumbre auditada pertenece a otro candidateId.")
        if self._sha256(
            uncertainty.get("candidateFingerprint"), "uncertainty.candidateFingerprint"
        ) != candidate_fingerprint:
            raise ValueError("La incertidumbre auditada pertenece a otro fingerprint.")
        if self._required_text(uncertainty.get("symbol"), "uncertainty.symbol").upper() != self._required_text(
            candidate.get("symbol"), "candidate.symbol"
        ).upper():
            raise ValueError("La incertidumbre auditada pertenece a otro símbolo.")
        if self._aware(uncertainty.get("asOf"), "uncertainty.asOf") != self._aware(
            candidate.get("asOf"), "candidate.asOf"
        ):
            raise ValueError("La incertidumbre auditada pertenece a otro instante de corte.")
        if uncertainty.get("advisoryStatus") != "no_advice":
            raise ValueError("La incertidumbre auditada debe mantener no_advice.")
        if uncertainty.get("productionEligible") is not False:
            raise ValueError("La incertidumbre auditada debe mantener productionEligible=False.")
        if uncertainty.get("recommendationCandidateReady") is not False:
            raise ValueError("La incertidumbre auditada no puede habilitar recomendaciones.")
        if uncertainty.get("actionThresholdCalibrationResearchEligible") is not False:
            raise ValueError("La incertidumbre auditada no puede promover calibración.")
        if uncertainty.get("action") is not None or uncertainty.get("conviction") is not None:
            raise ValueError("La incertidumbre auditada no puede contener acción o convicción.")
        policy = uncertainty.get("policy")
        if not isinstance(policy, dict) or policy.get("cutoff") != "candidate_as_of_not_request_time":
            raise ValueError("La incertidumbre auditada no conserva su cutoff ex-ante.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    def _required_text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _sha256(self, value: object, field: str) -> str:
        result = self._required_text(value, field).lower()
        if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result

    def _aware(self, value: object, field: str) -> datetime:
        raw = self._required_text(value, field)
        try:
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return result.astimezone(timezone.utc)
