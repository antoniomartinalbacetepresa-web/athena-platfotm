from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.services.recommendation_athena_radar_service import AthenaRadarEvidenceInput


@dataclass(frozen=True)
class InvestorDocumentInput:
    issuer_id: str
    document_type: str
    title: str
    provider: str
    primary_source: str
    document_url: str
    published_at: datetime
    retrieved_at: datetime


class RecommendationInvestorEvidenceService:
    """Convert primary investor/filing documents into PIT Radar evidence.

    This boundary preserves document provenance. It does not infer truth,
    investment impact, recommendation scores, or source independence.
    """

    _ALLOWED_DOCUMENT_TYPES = frozenset({"sec_filing", "annual_report", "quarterly_report", "earnings_release", "investor_presentation"})

    def build(self, *, document: InvestorDocumentInput, urgency: str = "routine") -> AthenaRadarEvidenceInput:
        issuer_id = self._text(document.issuer_id, "issuer_id")
        document_type = self._text(document.document_type, "document_type").lower()
        if document_type not in self._ALLOWED_DOCUMENT_TYPES:
            raise ValueError("document_type no está soportado para evidencia Investors.")
        title = self._text(document.title, "title")
        provider = self._text(document.provider, "provider")
        primary_source = self._text(document.primary_source, "primary_source")
        document_url = self._https(document.document_url, "document_url")
        published_at = self._aware(document.published_at, "published_at")
        retrieved_at = self._aware(document.retrieved_at, "retrieved_at")
        if published_at > retrieved_at:
            raise ValueError("published_at no puede ser posterior a retrieved_at; evitar look-ahead es obligatorio.")
        lowered = f"{provider} {primary_source} {document_url}".casefold().replace(" ", "")
        if "financialmodelingprep" in lowered or provider.casefold() == "fmp":
            raise ValueError("FMP/Financial Modeling Prep no está permitido.")
        identity = "|".join((issuer_id.casefold(), document_type, primary_source.casefold(), document_url.casefold(), published_at.isoformat()))
        evidence_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return AthenaRadarEvidenceInput(
            evidence_id=evidence_id,
            category="investors",
            urgency=urgency,
            summary=title,
            available_at=retrieved_at,
            source=primary_source,
            source_ref=document_url,
            provider=provider,
            publisher=primary_source,
            published_at=published_at,
        )

    def policy(self) -> dict[str, object]:
        return {
            "status": "structured_investor_provenance_ready",
            "productionTruthClaimed": False,
            "independentCorroborationClaimed": False,
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _https(self, value: object, field: str) -> str:
        text = self._text(value, field)
        parsed = urlparse(text)
        if parsed.scheme.casefold() != "https" or not parsed.netloc:
            raise ValueError(f"{field} debe ser una URL HTTPS absoluta.")
        return text

    def _aware(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
