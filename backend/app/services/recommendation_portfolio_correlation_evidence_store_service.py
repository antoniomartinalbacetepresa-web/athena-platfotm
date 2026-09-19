from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Protocol

from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.services.portfolio_correlation_service import PortfolioCorrelationService


class _CorrelationService(Protocol):
    def calculate_pair(
        self,
        *,
        left_instrument_id: int,
        right_instrument_id: int,
        source_provider: str,
        knowledge_cutoff: datetime,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
    ) -> Any: ...


class _Repository(Protocol):
    def seal(self, *, artifact: dict[str, Any]) -> dict[str, Any]: ...

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]: ...


class RecommendationPortfolioCorrelationEvidenceStoreService:
    """Compute PIT correlation from backend observations and seal the exact result."""

    ARTIFACT_VERSION = "athena-portfolio-correlation-evidence-v1"

    def __init__(
        self,
        *,
        correlation_service: _CorrelationService | None = None,
        repository: _Repository | None = None,
    ) -> None:
        self._correlation_service = correlation_service or PortfolioCorrelationService()
        self._repository = repository or RecommendationPortfolioCorrelationEvidenceRepository()

    def calculate_and_seal(
        self,
        *,
        left_instrument_id: int,
        right_instrument_id: int,
        source_provider: str,
        knowledge_cutoff: datetime,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
    ) -> dict[str, Any]:
        result = self._correlation_service.calculate_pair(
            left_instrument_id=left_instrument_id,
            right_instrument_id=right_instrument_id,
            source_provider=source_provider,
            knowledge_cutoff=knowledge_cutoff,
            observed_from=observed_from,
            observed_to=observed_to,
        )
        if not hasattr(result, "to_api_dict"):
            raise ValueError("El servicio de correlación no devolvió un resultado verificable.")
        payload = result.to_api_dict()
        if not isinstance(payload, dict):
            raise ValueError("El resultado de correlación no es un objeto válido.")
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "leftInstrumentId": payload.get("leftInstrumentId"),
            "rightInstrumentId": payload.get("rightInstrumentId"),
            "sourceProvider": payload.get("sourceProvider"),
            "knowledgeCutoff": payload.get("knowledgeCutoff"),
            "sampleCount": payload.get("sampleCount"),
            "correlation": payload.get("correlation"),
            "firstReturnDate": payload.get("firstReturnDate"),
            "lastReturnDate": payload.get("lastReturnDate"),
            "latestRetrievedAt": payload.get("latestRetrievedAt"),
            "priceField": payload.get("priceField"),
            "alignmentPolicy": payload.get("alignmentPolicy"),
            "returnPolicy": payload.get("returnPolicy"),
        }
        artifact = {
            "status": "portfolio_correlation_evidence_verified_non_advisory",
            **core,
            "portfolioCorrelationEvidenceFingerprint": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }
        record = self._repository.seal(artifact=artifact)
        if not isinstance(record, dict):
            raise ValueError("El repositorio no devolvió un registro de correlación válido.")
        if self._repository.validate_record(record) is not record:
            raise ValueError("El repositorio sustituyó el registro de correlación sellado.")
        persisted = record.get("artifact")
        if not isinstance(persisted, dict) or persisted != artifact:
            raise ValueError("La correlación persistida difiere de la calculada por backend.")
        return {
            "status": "portfolio_correlation_evidence_sealed_non_advisory",
            "evidence": persisted,
            "evidenceFingerprint": record.get("evidence_fingerprint"),
            "recordFingerprint": record.get("record_fingerprint"),
            "persistedAt": record.get("persisted_at"),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

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
            raise ValueError("La correlación contiene datos no serializables o no finitos.") from exc
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
