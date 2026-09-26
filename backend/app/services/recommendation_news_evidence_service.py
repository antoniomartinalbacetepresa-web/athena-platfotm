from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlparse

from app.services.google_news_service import GoogleNewsService
from app.services.recommendation_athena_radar_service import AthenaRadarEvidenceInput


class RecommendationNewsEvidenceService:
    """Translate observed Google News items into PIT-safe ATHENA Radar evidence.

    The adapter preserves retrieval time separately from publication time. It
    provides traceability only: aggregation by Google News is not independent
    corroboration and does not establish article truth or investment merit.
    """

    _EXPECTED_PROVIDER = "google_news_rss"

    def __init__(self, news_service: GoogleNewsService | None = None) -> None:
        self._news_service = news_service or GoogleNewsService()

    def build_company_evidence(
        self,
        *,
        company_name: str,
        symbol: str,
        limit: int = 8,
        urgency: str = "routine",
    ) -> dict:
        normalized_company = self._required_text(company_name, "company_name")
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        if urgency not in {"routine", "material", "critical"}:
            raise ValueError("urgency debe ser routine, material o critical")

        feed = self._news_service.get_feed(
            query=f'"{normalized_company}" {normalized_symbol}',
            limit=limit,
        )
        provider = self._required_text(feed.get("sourceProvider"), "sourceProvider")
        if provider != self._EXPECTED_PROVIDER:
            raise ValueError("El proveedor de noticias no coincide con la provenance esperada")

        accepted: list[AthenaRadarEvidenceInput] = []
        rejected_count = 0
        seen_urls: set[str] = set()
        for item in feed.get("items", []):
            try:
                evidence = self._to_evidence(
                    item=item,
                    expected_provider=provider,
                    urgency=urgency,
                )
            except (TypeError, ValueError):
                rejected_count += 1
                continue
            normalized_url = evidence.source_ref.casefold()
            if normalized_url in seen_urls:
                rejected_count += 1
                continue
            seen_urls.add(normalized_url)
            accepted.append(evidence)

        return {
            "status": "news_evidence_ready" if accepted else "news_evidence_unavailable",
            "symbol": normalized_symbol,
            "sourceProvider": provider,
            "acceptedCount": len(accepted),
            "rejectedCount": rejected_count,
            "evidence": tuple(accepted),
            "provenanceComplete": bool(accepted),
            "productionTruthClaimed": False,
            "independentCorroborationClaimed": False,
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }

    def _to_evidence(
        self,
        *,
        item: object,
        expected_provider: str,
        urgency: str,
    ) -> AthenaRadarEvidenceInput:
        if not isinstance(item, dict):
            raise TypeError("Cada noticia debe ser un objeto estructurado")

        title = self._required_text(item.get("title"), "item.title")
        publisher = self._required_text(item.get("publisher"), "item.publisher")
        article_url = self._required_https_url(item.get("articleUrl"), "item.articleUrl")
        provider = self._required_text(item.get("sourceProvider"), "item.sourceProvider")
        if provider != expected_provider:
            raise ValueError("La noticia declara un proveedor distinto al feed")

        published_at = self._parse_aware_datetime(item.get("publishedAt"), "item.publishedAt")
        retrieved_at = self._parse_aware_datetime(item.get("retrievedAt"), "item.retrievedAt")
        if published_at > retrieved_at:
            raise ValueError("publishedAt no puede ser posterior a retrievedAt")

        evidence_digest = sha256(
            f"{provider}\n{article_url}\n{published_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        return AthenaRadarEvidenceInput(
            evidence_id=f"news:{evidence_digest}",
            category="news",
            urgency=urgency,
            summary=title,
            available_at=retrieved_at,
            source="news",
            source_ref=article_url,
            provider=provider,
            publisher=publisher,
            published_at=published_at,
        )

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio")
        return text

    @staticmethod
    def _required_https_url(value: object, field: str) -> str:
        text = str(value or "").strip()
        try:
            parsed = urlparse(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser HTTPS") from exc
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"{field} debe ser HTTPS")
        return text

    @staticmethod
    def _parse_aware_datetime(value: object, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria")
        return parsed.astimezone(timezone.utc)
