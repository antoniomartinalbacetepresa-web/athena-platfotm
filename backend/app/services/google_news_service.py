from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlparse
import re
import xml.etree.ElementTree as ET

import httpx


class GoogleNewsService:
    """Fetches a real, keyless Google News RSS feed with explicit provenance.

    News remains parallel evidence only. This service does not score, rank, or
    alter ATHENA recommendation candidates.
    """

    _BASE_URL = "https://news.google.com/rss/search"
    _DEFAULT_QUERY = "stock market earnings economy"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "ATHENA-TYCHE/0.1 news-provenance"},
        )

    def get_feed(
        self,
        *,
        query: str | None = None,
        limit: int = 8,
        language: str = "en",
        country: str = "US",
    ) -> dict:
        normalized_query = self._normalize_query(query)
        normalized_limit = self._normalize_limit(limit)
        normalized_language = self._normalize_locale_part(language, "language")
        normalized_country = self._normalize_locale_part(country, "country")

        params = {
            "q": normalized_query,
            "hl": f"{normalized_language}-{normalized_country}",
            "gl": normalized_country,
            "ceid": f"{normalized_country}:{normalized_language}",
        }
        url = f"{self._BASE_URL}?{urlencode(params)}"
        response = self._client.get(url)
        response.raise_for_status()

        retrieved_at = datetime.now(timezone.utc)
        items = self._parse_items(
            response.text,
            retrieved_at=retrieved_at,
            limit=normalized_limit,
        )

        return {
            "status": "news_feed_ready",
            "query": normalized_query,
            "count": len(items),
            "sourceProvider": "google_news_rss",
            "retrievedAt": retrieved_at.isoformat(),
            "items": items,
            "policy": {
                "athenaRecommendationInfluence": False,
                "automaticScoring": False,
                "automaticTrading": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
        }

    @classmethod
    def _parse_items(
        cls,
        xml_text: str,
        *,
        retrieved_at: datetime,
        limit: int,
    ) -> list[dict]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise RuntimeError("Google News devolvió RSS inválido") from exc

        result: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for node in root.findall("./channel/item"):
            title = cls._text(node.find("title"))
            article_url = cls._text(node.find("link"))
            published_raw = cls._text(node.find("pubDate"))
            source_node = node.find("source")
            publisher = cls._text(source_node)
            publisher_url = (
                source_node.attrib.get("url", "").strip()
                if source_node is not None
                else ""
            )

            if not title or not publisher or not cls._is_https_url(article_url):
                continue
            published_at = cls._parse_published_at(published_raw)
            if published_at is None or published_at > retrieved_at:
                continue

            key = (cls._dedupe_text(title), cls._dedupe_text(publisher))
            if key in seen:
                continue
            seen.add(key)

            result.append(
                {
                    "title": title,
                    "publisher": publisher,
                    "publisherUrl": (
                        publisher_url if cls._is_https_url(publisher_url) else None
                    ),
                    "articleUrl": article_url,
                    "publishedAt": published_at.isoformat(),
                    "retrievedAt": retrieved_at.isoformat(),
                    "sourceProvider": "google_news_rss",
                }
            )

        result.sort(key=lambda item: item["publishedAt"], reverse=True)
        return result[:limit]

    @staticmethod
    def _text(node: ET.Element | None) -> str:
        if node is None or node.text is None:
            return ""
        return re.sub(r"\s+", " ", node.text).strip()

    @staticmethod
    def _parse_published_at(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _is_https_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        return parsed.scheme == "https" and bool(parsed.netloc)

    @staticmethod
    def _dedupe_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    @classmethod
    def _normalize_query(cls, query: str | None) -> str:
        value = cls._DEFAULT_QUERY if query is None else query.strip()
        if not value:
            raise ValueError("La consulta de noticias no puede estar vacía")
        if len(value) > 200:
            raise ValueError("La consulta de noticias es demasiado larga")
        return value

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit debe ser un entero")
        if not 1 <= limit <= 25:
            raise ValueError("limit debe estar entre 1 y 25")
        return limit

    @staticmethod
    def _normalize_locale_part(value: str, field: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z]{2}", normalized):
            raise ValueError(f"{field} debe usar un código de dos letras")
        return normalized.upper() if field == "country" else normalized.lower()
