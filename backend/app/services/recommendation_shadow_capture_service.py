from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.recommendation_shadow_repository import (
    RecommendationShadowRepository,
)
from app.services.recommendation_evidence_gate_service import (
    RecommendationEvidenceGateService,
)


class _EvidenceGateService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


class RecommendationShadowCaptureService:
    """Capture immutable PIT evidence for later calibration, without an action."""

    FEATURE_SCHEMA_VERSION = "shadow-evidence-v1"

    def __init__(
        self,
        *,
        repository: RecommendationShadowRepository | None = None,
        evidence_gate_service: _EvidenceGateService | None = None,
    ) -> None:
        self._repository = (
            repository if repository is not None else RecommendationShadowRepository()
        )
        self._gate = (
            evidence_gate_service
            if evidence_gate_service is not None
            else RecommendationEvidenceGateService()
        )

    def capture(
        self,
        *,
        symbol: str,
        as_of: datetime,
        captured_at: datetime | None = None,
        benchmark_symbol: str | None = None,
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        cutoff = self._aware_utc(as_of, "as_of")
        captured = self._aware_utc(
            captured_at if captured_at is not None else datetime.now(timezone.utc),
            "captured_at",
        )
        if captured < cutoff:
            raise ValueError("captured_at no puede ser anterior a as_of.")

        diagnostic = self._gate.evaluate(symbol=normalized_symbol, as_of=cutoff)
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El evidence gate no respeta el contrato de ATHENA.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("El evidence gate devolvió un contrato inválido.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("El evidence gate intentó declararse productivo.")
        if payload.get("recommendationCandidateReady") is not False:
            raise RuntimeError("El evidence gate intentó habilitar consejo.")
        if payload.get("status") != "evidence_ready_for_calibration":
            return {
                "status": "not_captured",
                "symbol": normalized_symbol,
                "asOf": cutoff.isoformat(),
                "snapshotId": None,
                "reason": "La evidencia no está lista para calibración en sombra.",
                "blockers": list(payload.get("blockers") or []),
                "advisoryStatus": "no_advice",
            }

        instrument_id = self._positive_int(payload.get("instrumentId"))
        market = payload.get("market")
        if instrument_id is None or not isinstance(market, dict):
            raise RuntimeError("El gate listo para calibración carece de identidad de mercado.")
        price = self._positive_float(market.get("latestPrice"))
        observed_at = self._parse_aware(market.get("latestObservedAt"), "latestObservedAt")
        retrieved_at = self._parse_aware(market.get("latestRetrievedAt"), "latestRetrievedAt")
        if price is None:
            raise RuntimeError("El gate listo para calibración carece de precio de entrada.")
        if observed_at > cutoff or retrieved_at > cutoff:
            raise RuntimeError("El gate contiene evidencia de mercado posterior al corte PIT.")

        snapshot_id = self._repository.create_snapshot(
            instrument_id=instrument_id,
            symbol=normalized_symbol,
            data_cutoff_at=cutoff,
            captured_at=captured,
            feature_schema_version=self.FEATURE_SCHEMA_VERSION,
            evidence_status=str(payload["status"]),
            entry_price=price,
            entry_observed_at=observed_at,
            entry_retrieved_at=retrieved_at,
            evidence_snapshot=payload,
            benchmark_symbol=benchmark_symbol,
        )
        return {
            "status": "captured_for_calibration",
            "symbol": normalized_symbol,
            "asOf": cutoff.isoformat(),
            "snapshotId": snapshot_id,
            "featureSchemaVersion": self.FEATURE_SCHEMA_VERSION,
            "advisoryStatus": "no_advice",
            "reason": (
                "Snapshot PIT guardado exclusivamente para calibración; no contiene "
                "acción, score de recomendación ni convicción."
            ),
        }

    def _positive_int(self, value: object) -> int | None:
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    def _positive_float(self, value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    def _parse_aware(self, value: object, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError(f"{field} es obligatorio en el evidence gate.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"{field} no es una fecha válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
