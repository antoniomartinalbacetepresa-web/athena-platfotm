from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.repositories.instrument_repository import InstrumentRepository
from app.services.recommendation_book_to_market_evidence_service import (
    RecommendationBookToMarketEvidenceService,
)
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolver


class RecommendationValueFactorExposureService:
    """Derive bounded issuer-deduplicated PIT value exposure from sealed book-to-market evidence."""

    MIN_UNIVERSE = 20

    def __init__(
        self,
        *,
        instrument_repository: InstrumentRepository | None = None,
        cik_resolver: SecInstrumentCikResolver | None = None,
        book_to_market_service: RecommendationBookToMarketEvidenceService | None = None,
    ) -> None:
        self._instrument_repository = instrument_repository or InstrumentRepository()
        self._cik_resolver = cik_resolver or SecInstrumentCikResolver()
        self._book_to_market_service = book_to_market_service or RecommendationBookToMarketEvidenceService()

    def evaluate(self, *, instrument_id: int, as_of: datetime) -> dict[str, Any]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser entero positivo.")
        cutoff = self._utc(as_of, "as_of")
        instruments = [
            item
            for item in self._instrument_repository.list_active()
            if item.get("instrument_type") == "common_stock" and item.get("is_primary_listing") == 1
        ]
        if not instruments:
            raise ValueError("No hay common_stock primarios activos para construir value.")

        issuer_groups: dict[int, list[dict[str, Any]]] = {}
        resolutions: dict[int, Any] = {}
        for instrument in instruments:
            current_id = self._instrument_id(instrument.get("id"))
            try:
                resolution = self._cik_resolver.resolve(instrument_id=current_id)
            except ValueError:
                # Absence/ambiguity of SEC identity makes the instrument ineligible;
                # it is never guessed into the cross-section.
                continue
            resolutions[current_id] = resolution
            issuer_groups.setdefault(int(resolution.issuer_id), []).append(instrument)

        duplicate_issuer_ids = {
            issuer_id for issuer_id, members in issuer_groups.items() if len(members) != 1
        }
        unique_instruments = [
            members[0]
            for issuer_id, members in issuer_groups.items()
            if issuer_id not in duplicate_issuer_ids
        ]
        target_resolution = resolutions.get(instrument_id)
        if target_resolution is None:
            raise ValueError("El instrumento target no tiene identidad SEC canónica única.")
        if int(target_resolution.issuer_id) in duplicate_issuer_ids:
            raise ValueError("El emisor target tiene múltiples listings primarios y no entra en value.")

        entries: list[dict[str, Any]] = []
        for instrument in sorted(unique_instruments, key=lambda item: int(item["id"])):
            current_id = self._instrument_id(instrument.get("id"))
            evidence = self._book_to_market_service.evaluate(
                instrument_id=current_id,
                as_of=cutoff,
            )
            if evidence.get("status") != "resolved":
                continue
            ratio = self._positive(evidence.get("bookToMarket"), "bookToMarket")
            evidence_key = str(evidence.get("evidenceKey") or "")
            if not self._sha256(evidence_key):
                raise ValueError("Book-to-market resuelto carece de evidenceKey válida.")
            resolution = resolutions[current_id]
            entries.append(
                {
                    "instrumentId": current_id,
                    "issuerId": int(resolution.issuer_id),
                    "cik": str(resolution.cik),
                    "bookToMarket": ratio,
                    "bookToMarketEvidenceKey": evidence_key,
                }
            )

        if len(entries) < self.MIN_UNIVERSE:
            raise ValueError(
                f"Se requieren al menos {self.MIN_UNIVERSE} emisores únicos con book-to-market PIT resuelto."
            )
        by_id = {entry["instrumentId"]: entry for entry in entries}
        if instrument_id not in by_id:
            raise ValueError("El instrumento target no tiene book-to-market PIT válido en el universo.")
        target = by_id[instrument_id]
        target_ratio = float(target["bookToMarket"])
        ratios = sorted(float(entry["bookToMarket"]) for entry in entries)
        less = sum(value < target_ratio for value in ratios)
        equal = sum(value == target_ratio for value in ratios)
        average_rank = less + (equal - 1) / 2.0
        percentile = average_rank / (len(ratios) - 1)
        value_exposure = self._finite(2.0 * percentile - 1.0, "value")
        if value_exposure < -1.0 - 1e-12 or value_exposure > 1.0 + 1e-12:
            raise RuntimeError("El rank de value quedó fuera de [-1,1].")

        canonical_entries = [
            {
                "instrumentId": int(entry["instrumentId"]),
                "issuerId": int(entry["issuerId"]),
                "cik": str(entry["cik"]),
                "bookToMarket": format(float(entry["bookToMarket"]), ".17g"),
                "bookToMarketEvidenceKey": str(entry["bookToMarketEvidenceKey"]),
            }
            for entry in sorted(entries, key=lambda item: (int(item["issuerId"]), int(item["instrumentId"])))
        ]
        universe_fingerprint = hashlib.sha256(
            json.dumps(canonical_entries, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        artifact: dict[str, Any] = {
            "module": "pit_value_factor_exposure",
            "instrumentId": instrument_id,
            "asOf": cutoff.isoformat(),
            "availableAt": cutoff.isoformat(),
            "bookToMarket": target_ratio,
            "bookToMarketEvidenceKey": str(target["bookToMarketEvidenceKey"]),
            "issuerId": int(target["issuerId"]),
            "cik": str(target["cik"]),
            "universeCount": len(entries),
            "universeFingerprint": universe_fingerprint,
            "factors": {"value": value_exposure},
            "provenance": {
                "universeRule": "active_primary_common_stock_unique_canonical_issuer_unique_sec_cik_resolved_book_to_market",
                "issuerDeduplication": "issuers_with_multiple_primary_listings_excluded",
                "targetBookToMarketEvidenceKey": str(target["bookToMarketEvidenceKey"]),
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "all_upstream_evidence_point_in_time_at_as_of",
                "estimator": "cross_sectional_book_to_market_rank_high_positive_low_negative_bounded_minus1_plus1",
                "universe": "active_primary_common_stock_unique_issuer_sec_pit_only",
                "thresholds": "not_calibrated",
                "missingEvidence": "excluded_never_imputed",
                "statisticalIndependence": "not_claimed",
                "purpose": "factor_risk_diagnostic_only",
            },
        }
        artifact["factorExposureKey"] = self._key(artifact)
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("module") != "pit_value_factor_exposure":
            raise ValueError("Value factor artifact tiene módulo inválido.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Value factor artifact violó no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("Value factor intentó habilitar producción/weighting.")
        count = artifact.get("universeCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < self.MIN_UNIVERSE:
            raise ValueError("Value factor carece de universo suficiente.")
        factors = artifact.get("factors")
        if not isinstance(factors, dict) or set(factors) != {"value"}:
            raise ValueError("Value factor debe contener exclusivamente value.")
        value = self._finite(factors["value"], "factors.value")
        if value < -1.0 - 1e-12 or value > 1.0 + 1e-12:
            raise ValueError("Value factor debe permanecer en [-1,1].")
        self._positive(artifact.get("bookToMarket"), "bookToMarket")
        if not self._sha256(str(artifact.get("bookToMarketEvidenceKey") or "")):
            raise ValueError("Value factor perdió bookToMarketEvidenceKey.")
        if not self._sha256(str(artifact.get("universeFingerprint") or "")):
            raise ValueError("Value factor perdió universeFingerprint.")
        as_of = self._parse(artifact.get("asOf"), "asOf")
        available = self._parse(artifact.get("availableAt"), "availableAt")
        if available > as_of:
            raise ValueError("Value factor viola PIT/no-lookahead.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False or policy.get("thresholds") != "not_calibrated":
            raise ValueError("Value factor perdió límites de seguridad/calibración.")
        if str(artifact.get("factorExposureKey") or "") != self._key(artifact):
            raise ValueError("factorExposureKey no coincide con value artifact canónico.")
        return artifact

    @staticmethod
    def _instrument_id(raw: object) -> int:
        if isinstance(raw, bool):
            raise ValueError("InstrumentRepository devolvió id inválido.")
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("InstrumentRepository devolvió id inválido.") from exc
        if value <= 0:
            raise ValueError("InstrumentRepository devolvió id inválido.")
        return value

    @staticmethod
    def _key(artifact: dict[str, Any]) -> str:
        canonical = {key: value for key, value in artifact.items() if key != "factorExposureKey"}
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _finite(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{field} debe ser finito.")
        return value

    @classmethod
    def _positive(cls, raw: object, field: str) -> float:
        value = cls._finite(raw, field)
        if value <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return value

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    @staticmethod
    def _utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse(cls, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return cls._utc(raw, field)
        text = str(raw or "").strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._utc(parsed, field)
