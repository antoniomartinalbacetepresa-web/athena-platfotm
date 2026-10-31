from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.repositories.recommendation_shadow_live_cycle_attestation_repository import (
    RecommendationShadowLiveCycleAttestationRepository,
)


class _AttestationRepository(Protocol):
    def save(
        self,
        *,
        candidate_id: int,
        candidate_fingerprint: str,
        artifact_version: str,
        artifact: dict[str, Any],
    ) -> int: ...

    def get_for_candidate(self, candidate_id: int) -> dict[str, Any] | None: ...


class RecommendationShadowLiveCycleAttestationService:
    """Seal provenance that a candidate completed the trusted persisted live cycle."""

    ARTIFACT_VERSION = "shadow-live-cycle-attestation-v1"

    def __init__(self, *, repository: _AttestationRepository | None = None) -> None:
        self._repository = repository or RecommendationShadowLiveCycleAttestationRepository()

    def attest_and_store(self, *, cycle_result: dict[str, Any]) -> dict[str, Any]:
        artifact = self._artifact(cycle_result)
        candidate_id = self._positive_int(artifact["candidateId"], "candidateId")
        candidate_fingerprint = self._sha256(
            artifact["candidateFingerprint"], "candidateFingerprint"
        )
        attestation_id = self._repository.save(
            candidate_id=candidate_id,
            candidate_fingerprint=candidate_fingerprint,
            artifact_version=self.ARTIFACT_VERSION,
            artifact=artifact,
        )
        stored = self.get_for_candidate(candidate_id=candidate_id)
        if stored is None:
            raise RuntimeError("La atestación live no pudo releerse tras persistirla.")
        if stored["attestationId"] != attestation_id:
            raise RuntimeError("La identidad de la atestación live cambió tras persistirla.")
        return stored

    def get_for_candidate(self, *, candidate_id: int) -> dict[str, Any] | None:
        row = self._repository.get_for_candidate(candidate_id)
        if row is None:
            return None
        artifact = row.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError("La atestación persistida carece de artefacto válido.")
        self.validate_artifact(artifact)
        persisted_fingerprint = self._sha256(
            row.get("attestation_fingerprint"), "attestation_fingerprint"
        )
        calculated_fingerprint = self._fingerprint(artifact)
        if persisted_fingerprint != calculated_fingerprint:
            raise ValueError("La huella persistida no coincide con la atestación live.")
        if self._positive_int(row.get("candidate_id"), "candidate_id") != self._positive_int(
            artifact.get("candidateId"), "candidateId"
        ):
            raise ValueError("La atestación fue vinculada a otro candidateId.")
        if self._sha256(
            row.get("candidate_fingerprint"), "candidate_fingerprint"
        ) != self._sha256(artifact.get("candidateFingerprint"), "candidateFingerprint"):
            raise ValueError("La atestación fue vinculada a otro candidateFingerprint.")
        return {
            "status": "shadow_live_cycle_attestation_available",
            "attestationId": self._positive_int(row.get("id"), "attestation.id"),
            "attestationFingerprint": persisted_fingerprint,
            **artifact,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("La atestación live debe ser un objeto.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de atestación live no compatible.")
        self._positive_int(artifact.get("candidateId"), "candidateId")
        self._positive_int(artifact.get("snapshotId"), "snapshotId")
        self._sha256(artifact.get("candidateFingerprint"), "candidateFingerprint")
        self._sha256(
            artifact.get("confirmationEvidenceFingerprint"),
            "confirmationEvidenceFingerprint",
        )
        self._sha256(artifact.get("uncertaintyFingerprint"), "uncertaintyFingerprint")
        self._sha256(
            artifact.get("decisionResearchFingerprint"),
            "decisionResearchFingerprint",
        )
        fingerprints = artifact.get("bundleFingerprints")
        if not isinstance(fingerprints, list) or not fingerprints:
            raise ValueError("La atestación debe contener frozen bundle fingerprints.")
        normalized = [self._sha256(item, "bundleFingerprint") for item in fingerprints]
        if len(set(normalized)) != len(normalized):
            raise ValueError("La atestación no puede repetir frozen bundle fingerprints.")
        if artifact.get("frozenCandidateSource") != "sqlite_persisted_and_revalidated":
            raise ValueError("La atestación exige frozen candidates persistidos y revalidados.")
        if artifact.get("callerSuppliedFrozenBundleJsonTrusted") is not False:
            raise ValueError("La atestación no puede confiar en frozen bundle JSON del caller.")
        if artifact.get("frozenBundleIntegrity") != "gated_freeze_revalidated_after_load":
            raise ValueError("La atestación exige revalidación gated-freeze tras la carga.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La atestación debe mantener advisoryStatus=no_advice.")
        if artifact.get("productionEligible") is not False:
            raise ValueError("La atestación debe mantener productionEligible=False.")
        if artifact.get("recommendationCandidateReady") is not False:
            raise ValueError("La atestación no puede habilitar recomendaciones.")
        return artifact

    def _artifact(self, cycle_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(cycle_result, dict):
            raise ValueError("cycle_result debe ser un objeto.")
        if cycle_result.get("status") != "shadow_live_cycle_persisted":
            raise ValueError("Sólo un ciclo live persistido puede ser atestado.")
        policy = cycle_result.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("El ciclo live confiable carece de policy.")
        candidate = cycle_result.get("candidate")
        decision = cycle_result.get("decisionResearch")
        if not isinstance(candidate, dict) or not isinstance(decision, dict):
            raise ValueError("El ciclo live carece de candidato o decision research.")

        candidate_fp = self._sha256(
            cycle_result.get("candidateFingerprint"), "candidateFingerprint"
        )
        uncertainty_fp = self._sha256(
            cycle_result.get("uncertaintyFingerprint"), "uncertaintyFingerprint"
        )
        decision_fp = self._sha256(
            cycle_result.get("decisionResearchFingerprint"),
            "decisionResearchFingerprint",
        )
        if self._sha256(candidate.get("candidateFingerprint"), "candidate.candidateFingerprint") != candidate_fp:
            raise ValueError("El candidato anidado no coincide con la identidad del ciclo.")
        if self._sha256(decision.get("candidateFingerprint"), "decision.candidateFingerprint") != candidate_fp:
            raise ValueError("Decision research no coincide con el candidato del ciclo.")
        if self._sha256(decision.get("uncertaintyFingerprint"), "decision.uncertaintyFingerprint") != uncertainty_fp:
            raise ValueError("Decision research no coincide con la incertidumbre sellada.")
        if self._sha256(decision.get("decisionResearchFingerprint"), "decision.decisionResearchFingerprint") != decision_fp:
            raise ValueError("Decision research no coincide con su huella del ciclo.")

        fingerprints = cycle_result.get("bundleFingerprints")
        if not isinstance(fingerprints, list) or not fingerprints:
            raise ValueError("El ciclo live confiable debe exponer bundleFingerprints.")
        normalized_fingerprints = [
            self._sha256(item, "bundleFingerprint") for item in fingerprints
        ]
        if len(set(normalized_fingerprints)) != len(normalized_fingerprints):
            raise ValueError("Los bundleFingerprints confiables no pueden repetirse.")

        inferred = candidate.get("horizons")
        if not isinstance(inferred, dict):
            raise ValueError("El candidato live carece de horizontes.")
        trusted_bundle_set = set(normalized_fingerprints)
        for horizon in inferred.values():
            if not isinstance(horizon, dict):
                raise ValueError("Un horizonte live tiene formato inválido.")
            bundle_fp = horizon.get("bundleFingerprint")
            if bundle_fp is None:
                continue
            if self._sha256(bundle_fp, "candidate.bundleFingerprint") not in trusted_bundle_set:
                raise ValueError("El candidato live referencia un frozen bundle no atestado.")

        artifact = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "candidateId": self._positive_int(cycle_result.get("candidateId"), "candidateId"),
            "snapshotId": self._positive_int(cycle_result.get("snapshotId"), "snapshotId"),
            "candidateFingerprint": candidate_fp,
            "confirmationEvidenceFingerprint": self._sha256(
                cycle_result.get("confirmationEvidenceFingerprint"),
                "confirmationEvidenceFingerprint",
            ),
            "uncertaintyFingerprint": uncertainty_fp,
            "decisionResearchFingerprint": decision_fp,
            "symbol": self._required_text(cycle_result.get("symbol"), "symbol").upper(),
            "asOf": self._required_text(cycle_result.get("asOf"), "asOf"),
            "benchmarkSymbol": self._required_text(
                cycle_result.get("benchmarkSymbol"), "benchmarkSymbol"
            ).upper(),
            "bundleFingerprints": normalized_fingerprints,
            "frozenCandidateSource": cycle_result.get("frozenCandidateSource"),
            "callerSuppliedFrozenBundleJsonTrusted": policy.get(
                "callerSuppliedFrozenBundleJsonTrusted"
            ),
            "frozenBundleIntegrity": policy.get("frozenBundleIntegrity"),
            "advisoryStatus": cycle_result.get("advisoryStatus"),
            "productionEligible": cycle_result.get("productionEligible"),
            "recommendationCandidateReady": cycle_result.get(
                "recommendationCandidateReady"
            ),
        }
        self.validate_artifact(artifact)
        return artifact

    def _fingerprint(self, artifact: dict[str, Any]) -> str:
        canonical = json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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
        if len(result) != 64 or any(c not in "0123456789abcdef" for c in result):
            raise ValueError(f"{field} debe ser un SHA-256 hexadecimal.")
        return result
