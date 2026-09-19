from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.recommendation_shadow_live_candidate_repository import (
    RecommendationShadowLiveCandidateRepository,
)
from app.services.recommendation_shadow_live_candidate_service import (
    RecommendationShadowLiveCandidateService,
)


class RecommendationShadowLatestCandidateService:
    """Resolve the latest persisted shadow candidate known at one PIT cutoff.

    Selection is deliberately based on both the candidate's market-data cutoff and
    the repository persistence timestamp. A candidate with an old ``asOf`` that was
    only persisted later must not become visible to an earlier historical query.
    Every persisted record encountered is integrity-validated before it can be used.
    """

    def __init__(
        self,
        *,
        repository: RecommendationShadowLiveCandidateRepository | None = None,
        candidate_service: RecommendationShadowLiveCandidateService | None = None,
    ) -> None:
        self._repository = repository or RecommendationShadowLiveCandidateRepository()
        self._candidate_service = candidate_service or RecommendationShadowLiveCandidateService()

    def resolve(self, *, as_of: datetime) -> dict[str, Any]:
        cutoff = self._aware_utc(as_of, "as_of")
        eligible: list[tuple[datetime, datetime, int, dict[str, Any]]] = []

        for record in self._repository.list_all():
            if not isinstance(record, dict):
                raise ValueError("El repositorio devolvió un registro live inválido.")
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("El registro live persistido carece de artifact.")
            validated = self._candidate_service.validate_artifact(artifact)
            if validated is not artifact:
                raise ValueError("El validador sustituyó el candidato live persistido.")

            candidate_fingerprint = self._sha256(
                artifact.get("candidateFingerprint"), "artifact.candidateFingerprint"
            )
            if candidate_fingerprint != self._sha256(
                record.get("candidate_fingerprint"), "record.candidate_fingerprint"
            ):
                raise ValueError("El fingerprint persistido no coincide con el candidato live.")
            if str(record.get("artifact_version") or "") != str(
                artifact.get("artifactVersion") or ""
            ):
                raise ValueError("La versión persistida no coincide con el candidato live.")
            if str(record.get("confirmation_fingerprint") or "") != str(
                artifact.get("confirmationEvidenceFingerprint") or ""
            ):
                raise ValueError("La confirmación persistida no coincide con el candidato live.")

            candidate_as_of = self._parse_aware(artifact.get("asOf"), "artifact.asOf")
            persisted_at = self._parse_aware(record.get("created_at"), "record.created_at")
            if candidate_as_of > persisted_at:
                raise ValueError("Un candidato live fue persistido antes de su propio corte PIT.")
            if candidate_as_of > cutoff or persisted_at > cutoff:
                continue

            record_id = record.get("id")
            if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id <= 0:
                raise ValueError("El registro live persistido tiene id inválido.")
            eligible.append((candidate_as_of, persisted_at, record_id, artifact))

        if not eligible:
            return {
                "status": "no_shadow_candidate_known_at_cutoff",
                "asOf": cutoff.isoformat(),
                "candidate": None,
                "advisoryStatus": "no_advice",
                "recommendationCandidateReady": False,
                "productionEligible": False,
                "automaticTrading": False,
            }

        candidate_as_of, persisted_at, record_id, artifact = max(
            eligible,
            key=lambda item: (item[0], item[1], item[2]),
        )
        return {
            "status": "shadow_candidate_available_non_advisory",
            "asOf": cutoff.isoformat(),
            "candidateAsOf": candidate_as_of.isoformat(),
            "persistedAt": persisted_at.isoformat(),
            "recordId": record_id,
            "candidate": artifact,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "automaticTrading": False,
        }

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _parse_aware(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        return self._aware_utc(parsed, field)

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
            raise ValueError(f"{field} debe ser SHA-256 válido.")
        return result
