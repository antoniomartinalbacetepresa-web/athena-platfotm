from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

from app.repositories.issuer_identity_repository import IssuerIdentityRepository


@dataclass(frozen=True)
class SecInstrumentCikResolution:
    instrument_id: int
    issuer_id: int
    cik: str
    issuer_name: str
    link_confidence: float
    external_id_confidence: float
    evidence_source: str
    resolution_method: str
    identity_key: str

    def to_api_dict(self) -> dict[str, object]:
        return {
            "module": "sec_instrument_cik_resolution",
            "instrumentId": self.instrument_id,
            "issuerId": self.issuer_id,
            "cik": self.cik,
            "issuerName": self.issuer_name,
            "linkConfidence": self.link_confidence,
            "externalIdConfidence": self.external_id_confidence,
            "evidenceSource": self.evidence_source,
            "resolutionMethod": self.resolution_method,
            "identityKey": self.identity_key,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "externalIdProvider": "sec_edgar",
                "uniqueSecCikRequired": True,
                "confidenceThreshold": "none_selected_here",
                "ambiguousIdentity": "fail_closed",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class SecInstrumentCikResolver:
    """Resolve instrument -> canonical issuer -> unique SEC CIK without guessing."""

    _SEC_PROVIDER = "sec_edgar"

    def __init__(self, repository: IssuerIdentityRepository | None = None) -> None:
        self._repository = repository or IssuerIdentityRepository()

    def resolve(self, *, instrument_id: int) -> SecInstrumentCikResolution:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        issuer = self._repository.get_issuer_for_instrument(instrument_id)
        if issuer is None:
            raise ValueError("El instrumento no tiene emisor canónico resuelto.")
        issuer_id = self._positive_int(issuer.get("issuer_id"), "issuer_id")
        issuer_name = self._text(issuer.get("canonical_name"), "canonical_name")
        evidence_source = self._text(issuer.get("evidence_source"), "evidence_source")
        resolution_method = self._text(issuer.get("resolution_method"), "resolution_method")
        link_confidence = self._confidence(issuer.get("confidence"), "confidence")

        external_ids = self._repository.list_external_ids(issuer_id)
        sec_ids = [
            item
            for item in external_ids
            if str(item.get("source_provider") or "").strip().casefold() == self._SEC_PROVIDER
        ]
        if not sec_ids:
            raise ValueError("El emisor canónico no tiene CIK SEC explícito.")
        normalized: dict[str, float] = {}
        for item in sec_ids:
            cik = self._cik(item.get("external_id"))
            confidence = self._confidence(
                item.get("evidence_confidence"),
                "evidence_confidence",
            )
            previous = normalized.get(cik)
            if previous is None or confidence > previous:
                normalized[cik] = confidence
        if len(normalized) != 1:
            raise ValueError("El emisor canónico tiene múltiples CIK SEC y la identidad es ambigua.")
        cik, external_confidence = next(iter(normalized.items()))

        identity = {
            "instrumentId": instrument_id,
            "issuerId": issuer_id,
            "cik": cik,
            "issuerName": issuer_name,
            "linkConfidence": format(link_confidence, ".17g"),
            "externalIdConfidence": format(external_confidence, ".17g"),
            "evidenceSource": evidence_source,
            "resolutionMethod": resolution_method,
            "externalIdProvider": self._SEC_PROVIDER,
        }
        key = hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return SecInstrumentCikResolution(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            cik=cik,
            issuer_name=issuer_name,
            link_confidence=link_confidence,
            external_id_confidence=external_confidence,
            evidence_source=evidence_source,
            resolution_method=resolution_method,
            identity_key=key,
        )

    @staticmethod
    def _text(raw: object, field: str) -> str:
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"{field} es obligatorio.")
        return value

    @staticmethod
    def _positive_int(raw: object, field: str) -> int:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe ser positivo.")
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser positivo.") from exc
        if value <= 0:
            raise ValueError(f"{field} debe ser positivo.")
        return value

    @staticmethod
    def _confidence(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe estar entre 0 y 1.") from exc
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        return value

    @staticmethod
    def _cik(raw: object) -> str:
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if not digits or len(digits) > 10:
            raise ValueError("CIK SEC inválido.")
        return digits.zfill(10)
