from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
import re
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class NewsSynthesisItem:
    title: str
    publisher: str
    article_url: str
    published_at: str
    retrieved_at: str
    source_provider: str
    evidence_id: str
    importance_score: float
    importance: str
    estimated_impact: str
    rationale: tuple[str, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "publisher": self.publisher,
            "articleUrl": self.article_url,
            "publishedAt": self.published_at,
            "retrievedAt": self.retrieved_at,
            "sourceProvider": self.source_provider,
            "evidenceId": self.evidence_id,
            "importanceScore": self.importance_score,
            "importance": self.importance,
            "estimatedImpact": self.estimated_impact,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class NewsSynthesisReport:
    items: tuple[NewsSynthesisItem, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "count": len(self.items),
            "items": [item.to_api_dict() for item in self.items],
            "policy": {
                "automaticAthenaScoreImpact": False,
                "automaticRecommendationImpact": False,
                "automaticTrading": False,
                "duplicateEvidenceAmplification": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "warning": (
                "La importancia y el impacto son clasificaciones heurísticas y trazables; "
                "no son predicciones, no modifican el ATHENA Score ni autorizan recomendaciones."
            ),
        }


class NewsSynthesisService:
    """Transparent, deterministic synthesis over already-provenanced news evidence."""

    _HIGH = ("earnings", "guidance", "acquisition", "merger", "bankruptcy", "default", "fraud", "sec", "lawsuit", "rate cut", "rate hike")
    _MEDIUM = ("revenue", "profit", "inflation", "jobs", "tariff", "regulation", "dividend", "buyback", "launch")
    _POSITIVE = ("beats", "beat estimates", "raises guidance", "record profit", "approval", "wins", "buyback", "dividend increase")
    _NEGATIVE = ("misses", "cuts guidance", "bankruptcy", "default", "fraud", "investigation", "recall", "lawsuit", "downgrade")

    def synthesize(self, items: Iterable[dict[str, Any]]) -> NewsSynthesisReport:
        normalized: list[NewsSynthesisItem] = []
        seen_evidence: set[str] = set()
        seen_urls: set[str] = set()
        for raw in items:
            item = self._normalize(raw)
            if item.article_url in seen_urls or item.evidence_id in seen_evidence:
                raise ValueError(
                    "El feed contiene evidencia de noticia duplicada; no puede amplificar la síntesis."
                )
            seen_urls.add(item.article_url)
            seen_evidence.add(item.evidence_id)
            normalized.append(item)
        normalized.sort(key=lambda item: (-item.importance_score, item.published_at, item.title))
        return NewsSynthesisReport(items=tuple(normalized))

    def _normalize(self, item: dict[str, Any]) -> NewsSynthesisItem:
        if not isinstance(item, dict):
            raise ValueError("Cada noticia debe ser un objeto con provenance explícita")
        title = self._required_text(item.get("title"), "title")
        publisher = self._required_text(item.get("publisher"), "publisher")
        article_url = self._https_url(item.get("articleUrl"), "articleUrl")
        source_provider = self._required_text(item.get("sourceProvider"), "sourceProvider")
        published_at = self._timestamp(item.get("publishedAt"), "publishedAt")
        retrieved_at = self._timestamp(item.get("retrievedAt"), "retrievedAt")
        if published_at > retrieved_at:
            raise ValueError("publishedAt no puede ser posterior a retrievedAt")

        evidence_id = hashlib.sha256(
            "\n".join(
                (
                    source_provider.casefold(),
                    publisher.casefold(),
                    article_url,
                    published_at.isoformat(),
                )
            ).encode("utf-8")
        ).hexdigest()

        lowered = re.sub(r"\s+", " ", title).strip().casefold()
        high_hits = tuple(term for term in self._HIGH if term in lowered)
        medium_hits = tuple(term for term in self._MEDIUM if term in lowered)
        score = min(1.0, 0.25 + 0.35 * len(high_hits) + 0.15 * len(medium_hits))
        if not math.isfinite(score):
            raise ValueError("importanceScore debe ser finito")
        importance = "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"

        positive = tuple(term for term in self._POSITIVE if term in lowered)
        negative = tuple(term for term in self._NEGATIVE if term in lowered)
        if positive and negative:
            impact = "mixed"
        elif positive:
            impact = "potentially_positive"
        elif negative:
            impact = "potentially_negative"
        else:
            impact = "unclear"

        rationale = tuple(
            [*(f"high_signal:{term}" for term in high_hits), *(f"medium_signal:{term}" for term in medium_hits)]
        ) or ("no_material_keyword_signal",)

        return NewsSynthesisItem(
            title=title,
            publisher=publisher,
            article_url=article_url,
            published_at=published_at.isoformat(),
            retrieved_at=retrieved_at.isoformat(),
            source_provider=source_provider,
            evidence_id=evidence_id,
            importance_score=round(score, 4),
            importance=importance,
            estimated_impact=impact,
            rationale=rationale,
        )

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio")
        return text

    @staticmethod
    def _https_url(value: Any, field: str) -> str:
        text = NewsSynthesisService._required_text(value, field)
        try:
            parsed = urlsplit(text)
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"{field} no es una URL válida") from exc
        if parsed.scheme.casefold() != "https" or not parsed.hostname:
            raise ValueError(f"{field} debe ser una URL HTTPS absoluta")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"{field} no puede incluir credenciales")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError(f"{field} contiene un puerto no válido")
        host = parsed.hostname.casefold()
        if "." not in host and host != "localhost":
            raise ValueError(f"{field} debe incluir un host válido")
        netloc = host
        if parsed.port is not None:
            netloc = f"{host}:{parsed.port}"
        normalized = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
        return normalized

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es un timestamp ISO válido") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria")
        return parsed