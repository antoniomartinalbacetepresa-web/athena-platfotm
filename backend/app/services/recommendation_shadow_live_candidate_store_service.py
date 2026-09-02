from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class RecommendationShadowLiveCandidateStoreService:
    """Persist only validated live shadow inference tied to its PIT snapshot."""

    def __init__(
        self,
        *,
        repository: RecommendationShadowLiveCandidateRepository | None = None,
        snapshot_repository: RecommendationShadowRepository | None = None,
        candidate_service: RecommendationShadowLiveCandidateService | None = None,
    ) -> None:
        self._repository = repository or RecommendationShadowLiveCandidateRepository()
        self._snapshot_repository = snapshot_repository or RecommendationShadowRepository()
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()

    def store(
        self,
        *,
        snapshot_id: int,
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        validated = self._candidate_service.validate_artifact(candidate)
        self._assert_shadow(validated)
        if validated.get("status") != "shadow_live_candidate_inferred":
            raise ValueError("Sólo se pueden persistir candidatos live inferidos.")

        snapshot = self._snapshot_repository.get_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError("El snapshot PIT asociado no existe.")
        self._validate_snapshot_binding(snapshot, validated)

        fingerprint = self._required_text(
            validated.get("candidateFingerprint"), "candidateFingerprint"
        )
        confirmation = self._required_text(
            validated.get("confirmationEvidenceFingerprint"),
            "confirmationEvidenceFingerprint",
        )
        artifact_version = self._required_text(
            validated.get("artifactVersion"), "artifactVersion"
        )
        candidate_id = self._repository.save(
            snapshot_id=snapshot_id,
            candidate_fingerprint=fingerprint,
            confirmation_fingerprint=confirmation,
            artifact_version=artifact_version,
            artifact=validated,
        )
        persisted = self._repository.get(candidate_id)
        if persisted is None:
            raise RuntimeError("El candidato live no pudo releerse tras persistirlo.")
        if persisted.get("artifact") != validated:
            raise RuntimeError("El candidato live persistido no coincide con el validado.")
        if persisted.get("candidate_fingerprint") != fingerprint:
            raise RuntimeError("El fingerprint persistido no coincide con el candidato.")

        return {
            "status": "shadow_live_candidate_persisted",
            "candidateId": candidate_id,
            "snapshotId": snapshot_id,
            "candidateFingerprint": fingerprint,
            "confirmationEvidenceFingerprint": confirmation,
            "symbol": validated.get("symbol"),
            "asOf": validated.get("asOf"),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
            "policy": {
                "storage": "isolated_shadow_table",
                "pitSnapshotBindingRequired": True,
                "actions": "not_stored_as_columns",
                "score": "not_stored_as_column",
                "conviction": "not_stored_as_column",
                "automaticProductionPromotion": False,
            },
        }

    def _validate_snapshot_binding(
        self,
        snapshot: dict[str, Any],
        candidate: dict[str, Any],
    ) -> None:
        snapshot_symbol = str(snapshot.get("symbol") or "").strip().upper()
        candidate_symbol = str(candidate.get("symbol") or "").strip().upper()
        if snapshot_symbol != candidate_symbol:
            raise ValueError("El candidato no corresponde al símbolo del snapshot PIT.")

        try:
            snapshot_instrument_id = int(snapshot.get("instrument_id"))
            candidate_instrument_id = int(candidate.get("instrumentId"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Snapshot y candidato requieren instrument_id válido.") from exc
        if snapshot_instrument_id != candidate_instrument_id:
            raise ValueError("El candidato no corresponde al instrumento del snapshot PIT.")

        snapshot_cutoff = self._parse_aware(snapshot.get("data_cutoff_at"), "snapshot.data_cutoff_at")
        candidate_cutoff = self._parse_aware(candidate.get("asOf"), "candidate.asOf")
        if snapshot_cutoff != candidate_cutoff:
            raise ValueError("El candidato no corresponde al mismo corte PIT del snapshot.")

    def _assert_shadow(self, candidate: dict[str, Any]) -> None:
        if candidate.get("productionEligible") is not False:
            raise ValueError("El candidato persistido debe mantener productionEligible=False.")
        if candidate.get("advisoryStatus") != "no_advice":
            raise ValueError("El candidato persistido debe mantener no_advice.")
        if candidate.get("recommendationCandidateReady") is not False:
            raise ValueError("El candidato persistido no puede habilitar recomendación.")
        if candidate.get("action") is not None:
            raise ValueError("El candidato persistido no puede contener acción.")
        if candidate.get("score") is not None or candidate.get("conviction") is not None:
            raise ValueError("El candidato persistido no puede contener score o convicción.")

    def _parse_aware(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"{field} es obligatorio.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized
