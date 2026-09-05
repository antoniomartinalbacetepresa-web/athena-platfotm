from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.services.recommendation_verified_allocation_pipeline_service import (
    RecommendationVerifiedAllocationPipelineService,
)


class _CorrelationRepository(Protocol):
    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class _VerifiedPipeline(Protocol):
    def build(self, **kwargs: Any) -> dict[str, Any]: ...


class RecommendationAuthorizedAllocationPipelineService:
    """Authority boundary for allocation using only sealed correlation fingerprints.

    Raw correlation JSON remains an internal calculator input of the verified pipeline;
    it is not accepted at this authority boundary. Every correlation must have been
    computed from backend PIT observations and append-only sealed beforehand.
    """

    def __init__(
        self,
        *,
        correlation_repository: _CorrelationRepository | None = None,
        verified_pipeline: _VerifiedPipeline | None = None,
    ) -> None:
        self._correlation_repository = (
            correlation_repository
            or RecommendationPortfolioCorrelationEvidenceRepository()
        )
        self._verified_pipeline = (
            verified_pipeline or RecommendationVerifiedAllocationPipelineService()
        )

    def build(
        self,
        *,
        uncertainty_bound_action_candidate_fingerprint: str,
        allocation_policy_id: str,
        economic_contract: dict[str, Any],
        reference_capital: float,
        base_currency: str,
        positions: list[dict[str, Any]],
        correlation_evidence_fingerprints: list[str],
        as_of: datetime,
    ) -> dict[str, Any]:
        if not isinstance(correlation_evidence_fingerprints, list):
            raise ValueError("correlation_evidence_fingerprints debe ser una lista.")

        artifacts: list[dict[str, Any]] = []
        authorities: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        seen_pairs: set[tuple[int, int]] = set()
        for raw_fingerprint in correlation_evidence_fingerprints:
            fingerprint = self._sha256(raw_fingerprint, "correlationEvidenceFingerprint")
            if fingerprint in seen_fingerprints:
                raise ValueError("Se recibió un fingerprint de correlación duplicado.")
            seen_fingerprints.add(fingerprint)
            record = self._correlation_repository.get(evidence_fingerprint=fingerprint)
            if record is None:
                raise ValueError("La evidencia de correlación requerida no está sellada.")
            if self._correlation_repository.validate_record(record) is not record:
                raise ValueError("El repositorio sustituyó un registro de correlación sellado.")
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("El registro de correlación carece de artefacto válido.")
            if artifact.get("portfolioCorrelationEvidenceFingerprint") != fingerprint:
                raise ValueError("El artefacto de correlación no corresponde al registro sellado.")
            if record.get("evidence_fingerprint") != fingerprint:
                raise ValueError("El registro de correlación no corresponde al fingerprint solicitado.")
            if artifact.get("advisoryStatus") != "no_advice":
                raise ValueError("La correlación sellada intentó emitir advice.")
            for field in ("productionEligible", "allocationEligible", "automaticTrading"):
                if artifact.get(field) is not False:
                    raise ValueError(f"La correlación sellada violó {field}=False.")

            left = self._positive_int(artifact.get("leftInstrumentId"), "leftInstrumentId")
            right = self._positive_int(artifact.get("rightInstrumentId"), "rightInstrumentId")
            pair = tuple(sorted((left, right)))
            if pair in seen_pairs:
                raise ValueError("Se recibió más de una autoridad para el mismo par de correlación.")
            seen_pairs.add(pair)
            artifacts.append(artifact)
            authorities.append(
                {
                    "evidenceFingerprint": fingerprint,
                    "recordFingerprint": self._sha256(
                        record.get("record_fingerprint"), "correlationRecordFingerprint"
                    ),
                    "persistedAt": self._text(record.get("persisted_at"), "correlationPersistedAt"),
                    "leftInstrumentId": left,
                    "rightInstrumentId": right,
                }
            )

        result = self._verified_pipeline.build(
            uncertainty_bound_action_candidate_fingerprint=(
                uncertainty_bound_action_candidate_fingerprint
            ),
            allocation_policy_id=allocation_policy_id,
            economic_contract=economic_contract,
            reference_capital=reference_capital,
            base_currency=base_currency,
            positions=positions,
            correlation_evidence=artifacts,
            as_of=as_of,
        )
        if not isinstance(result, dict):
            raise ValueError("El pipeline verificado no devolvió un artefacto válido.")
        if result.get("advisoryStatus") != "no_advice":
            raise ValueError("El pipeline verificado intentó emitir advice.")
        for field in (
            "recommendationCandidateReady",
            "productionEligible",
            "allocationEligible",
            "automaticTrading",
        ):
            if result.get(field) is not False:
                raise ValueError(f"El pipeline verificado violó {field}=False.")

        return {
            **result,
            "correlationAuthority": authorities,
            "correlationAuthorityBoundToAllocation": True,
            "callerSuppliedCorrelationArtifactsAccepted": False,
            "policy": {
                **(result.get("policy") if isinstance(result.get("policy"), dict) else {}),
                "correlationMustResolveFromAppendOnlyBackendAuthority": True,
                "callerSuppliedCorrelationJsonAccepted": False,
                "automaticTrading": False,
            },
        }

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result
