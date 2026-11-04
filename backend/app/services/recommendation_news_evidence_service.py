from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re

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
        as_of: datetime | None = None,
    ) -> dict:
        normalized_company = self._required_text(company_name, "company_name")
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        if (len(normalized_company) > 100 or any(
            ord(char) < 32 or char == '"' for char in normalized_company
        )):
            raise ValueError("company_name contiene caracteres no permitidos")
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", normalized_symbol):
            raise ValueError("symbol debe identificar un símbolo bursátil válido")
        normalized_limit = GoogleNewsService._normalize_limit(limit)
        if urgency not in {"routine", "material", "critical"}:
            raise ValueError("urgency debe ser routine, material o critical")
        cutoff = None
        if as_of is not None:
            if (not isinstance(as_of, datetime) or as_of.tzinfo is None
                    or as_of.utcoffset() is None):
                raise ValueError("as_of debe incluir zona horaria")
            cutoff = as_of.astimezone(timezone.utc)
            if cutoff > datetime.now(timezone.utc):
                raise ValueError("as_of no puede estar en el futuro")

        query = f'"{normalized_company}" {normalized_symbol}'
        feed = self._news_service.get_feed(query=query, limit=normalized_limit)
        if not isinstance(feed, dict):
            raise ValueError("El feed de noticias debe ser un objeto estructurado")
        provider = self._required_text(feed.get("sourceProvider"), "sourceProvider")
        if provider != self._EXPECTED_PROVIDER:
            raise ValueError("El proveedor de noticias no coincide con la provenance esperada")
        policy = feed.get("policy")
        if (feed.get("status") != "news_feed_ready" or feed.get("query") != query
                or feed.get("advisoryStatus") != "no_advice"
                or feed.get("productionEligible") is not False
                or not isinstance(policy, dict)
                or any(policy.get(flag) is not False for flag in (
                    "athenaRecommendationInfluence", "automaticScoring", "automaticTrading"
                ))):
            raise ValueError("El feed de noticias perdió su identidad o política research-only")
        items = feed.get("items")
        if (not isinstance(items, list) or type(feed.get("count")) is not int
                or feed["count"] != len(items)):
            raise ValueError("El feed de noticias tiene un inventario incoherente")
        feed_retrieved = self._parse_aware_datetime(feed.get("retrievedAt"), "retrievedAt")
        if feed_retrieved > datetime.now(timezone.utc):
            raise ValueError("El feed de noticias declara una recuperación futura")

        accepted: list[AthenaRadarEvidenceInput] = []
        rejected_count = 0
        seen_urls: set[str] = set()
        for item in items:
            try:
                evidence = self._to_evidence(
                    item=item,
                    expected_provider=provider,
                    urgency=urgency,
                )
                if evidence.available_at > feed_retrieved:
                    raise ValueError("La noticia se recuperó después del feed")
                if cutoff is not None and evidence.available_at > cutoff:
                    raise ValueError("La noticia no estaba disponible en el corte PIT")
                # Search-engine results do not prove issuer identity.
                if not self._headline_mentions_issuer(
                    evidence.summary,
                    company_name=normalized_company,
                    symbol=normalized_symbol,
                ):
                    raise ValueError("El titular no menciona al emisor solicitado")
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
            "retrievedAt": feed_retrieved.isoformat(),
            "asOf": cutoff.isoformat() if cutoff is not None else None,
            "acceptedCount": len(accepted),
            "rejectedCount": rejected_count,
            "evidence": tuple(accepted),
            "provenanceComplete": bool(accepted),
            "productionTruthClaimed": False,
            "independentCorroborationClaimed": False,
            "issuerIdentityIndependentlyVerified": False,
            "headlineMentionRequired": True,
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
        if retrieved_at > datetime.now(timezone.utc):
            raise ValueError("retrievedAt no puede estar en el futuro")

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
    def _headline_mentions_issuer(
        title: str, *, company_name: str, symbol: str
    ) -> bool:
        """Conservative lexical filter; not independent issuer verification."""
        words = re.findall(r"[^\W_]+", company_name, flags=re.UNICODE)
        legal_suffixes = {
            "inc", "corp", "corporation", "ltd", "limited",
            "plc", "co", "company", "sa", "ag",
        }
        while words and words[-1].casefold() in legal_suffixes:
            words.pop()
        if words:
            phrase = r"\s+".join(re.escape(word) for word in words)
            if re.search(r"(?<!\w)" + phrase + r"(?!\w)", title, re.IGNORECASE):
                return True
        if len(symbol) >= 3 and re.search(
            r"(?<!\w)" + re.escape(symbol) + r"(?!\w)",
            title,
            re.IGNORECASE,
        ):
            return True
        return False

    @staticmethod
    def _required_https_url(value: object, field: str) -> str:
        text = str(value or "").strip()
        # Same strict URL contract as the feed: no credentials or backslashes.
        if not GoogleNewsService._is_https_url(text):
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
