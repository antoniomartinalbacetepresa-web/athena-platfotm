from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    AthenaRadarResult,
    RecommendationAthenaRadarService,
)


_IMPORTANCE_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_ALLOWED_IMPACT_DIRECTIONS = frozenset(
    {"negative", "neutral", "positive", "mixed", "uncertain"}
)
_FORBIDDEN_SOURCE_TOKENS = ("financialmodelingprep", "fmp")


@dataclass(frozen=True)
class NewsModelAssessmentInput:
    evidence_id: str
    model_provider: str
    model_name: str
    model_version: str
    input_fingerprint: str
    generated_at: datetime
    summary: str
    importance: str
    impact_direction: str
    impact_magnitude: float
    confidence: float


@dataclass(frozen=True)
class NewsSynthesisItem:
    evidence_id: str
    instrument_id: str
    symbol: str
    source_ref: str
    evidence_provider: str
    publisher: str
    published_at: str
    available_at: str
    model_provider: str
    model_name: str
    model_version: str
    generated_at: str
    input_fingerprint: str
    assessment_fingerprint: str
    summary: str
    importance: str
    impact_direction: str
    impact_magnitude: float
    confidence: float

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "sourceRef": self.source_ref,
            "evidenceProvider": self.evidence_provider,
            "publisher": self.publisher,
            "publishedAt": self.published_at,
            "availableAt": self.available_at,
            "modelProvider": self.model_provider,
            "modelName": self.model_name,
            "modelVersion": self.model_version,
            "generatedAt": self.generated_at,
            "inputFingerprint": self.input_fingerprint,
            "assessmentFingerprint": self.assessment_fingerprint,
            "summary": self.summary,
            "importance": self.importance,
            "impactDirection": self.impact_direction,
            "impactMagnitude": self.impact_magnitude,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class NewsSynthesisResult:
    as_of: str
    minimum_importance: str
    assessed_count: int
    included_count: int
    excluded_count: int
    assessments: tuple[NewsSynthesisItem, ...]
    items: tuple[NewsSynthesisItem, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "validated_external_model_output",
            "asOf": self.as_of,
            "minimumImportance": self.minimum_importance,
            "assessedCount": self.assessed_count,
            "includedCount": self.included_count,
            "excludedCount": self.excluded_count,
            "assessments": [item.to_api_dict() for item in self.assessments],
            "items": [item.to_api_dict() for item in self.items],
            "filteringInterpretation": (
                "items_is_filtered_research_view_while_assessments_preserves_complete_audit_coverage"
            ),
            "interpretation": {
                "importance": "external_model_research_triage_not_investment_score",
                "impact": "external_model_estimate_not_observed_fact",
                "summary": "external_model_output_not_source_truth",
            },
            "modelExecutionVerified": False,
            "productionTruthClaimed": False,
            "independentCorroborationClaimed": False,
            "recommendationInfluence": False,
            "automaticScoring": False,
            "automaticTrading": False,
        }


class RecommendationNewsSynthesisService:
    """Validate externally produced News synthesis against canonical PIT Radar evidence."""

    def __init__(self) -> None:
        self._radar = RecommendationAthenaRadarService()

    def build(
        self,
        *,
        radar_result: AthenaRadarResult,
        assessments: tuple[NewsModelAssessmentInput, ...],
        minimum_importance: str = "low",
    ) -> NewsSynthesisResult:
        canonical = self._canonical_radar(radar_result)
        as_of = self._aware_utc(
            datetime.fromisoformat(canonical.as_of.replace("Z", "+00:00")),
            "radar_result.as_of",
        )
        threshold = self._required_text(
            minimum_importance, "minimum_importance"
        ).lower()
        if threshold not in _IMPORTANCE_ORDER:
            raise ValueError(
                "minimum_importance debe ser low, medium, high o critical."
            )
        if not isinstance(assessments, tuple):
            raise ValueError("assessments debe ser una tupla.")
        if len(assessments) > 1000:
            raise ValueError("assessments no puede contener más de 1000 elementos.")

        news_evidence: dict[str, tuple[str, str, AthenaRadarEvidenceInput]] = {}
        for candidate in canonical.candidates:
            for evidence in candidate.evidence:
                if evidence.category == "news":
                    news_evidence[evidence.evidence_id] = (
                        candidate.instrument_id,
                        candidate.symbol,
                        evidence,
                    )

        if not news_evidence:
            raise ValueError(
                "ATHENA News synthesis requiere al menos una evidencia news canónica."
            )
        if len(assessments) != len(news_evidence):
            raise ValueError(
                "Debe existir exactamente una evaluación de modelo por cada evidencia news."
            )

        seen_assessments: set[str] = set()
        validated: list[NewsSynthesisItem] = []
        for raw in assessments:
            if not isinstance(raw, NewsModelAssessmentInput):
                raise ValueError(
                    "Cada assessment debe ser NewsModelAssessmentInput."
                )
            evidence_id = self._required_text(raw.evidence_id, "assessment.evidence_id")
            if evidence_id in seen_assessments:
                raise ValueError("assessment.evidence_id no puede repetirse.")
            seen_assessments.add(evidence_id)
            matched = news_evidence.get(evidence_id)
            if matched is None:
                raise ValueError(
                    "assessment.evidence_id no corresponde a evidencia news canónica."
                )
            instrument_id, symbol, evidence = matched

            expected_input_fingerprint = self.evidence_fingerprint(
                instrument_id=instrument_id,
                symbol=symbol,
                evidence=evidence,
            )
            supplied_fingerprint = self._required_text(
                raw.input_fingerprint, "assessment.input_fingerprint"
            ).lower()
            if supplied_fingerprint != expected_input_fingerprint:
                raise ValueError(
                    "assessment.input_fingerprint no coincide con la evidencia News canónica."
                )

            model_provider = self._required_text(
                raw.model_provider, "assessment.model_provider"
            )
            model_name = self._required_text(raw.model_name, "assessment.model_name")
            model_version = self._required_text(
                raw.model_version, "assessment.model_version"
            )
            self._assert_provider_allowed(model_provider)

            generated_at = self._aware_utc(
                raw.generated_at, "assessment.generated_at"
            )
            available_at = self._aware_utc(
                evidence.available_at, "evidence.available_at"
            )
            if generated_at < available_at:
                raise ValueError(
                    "assessment.generated_at no puede preceder la disponibilidad PIT de la noticia."
                )
            if generated_at > as_of:
                raise ValueError(
                    "assessment.generated_at no puede ser posterior a radar_result.as_of."
                )

            summary = self._required_text(raw.summary, "assessment.summary")
            if len(summary) > 4000:
                raise ValueError("assessment.summary no puede superar 4000 caracteres.")
            importance = self._required_text(
                raw.importance, "assessment.importance"
            ).lower()
            if importance not in _IMPORTANCE_ORDER:
                raise ValueError(
                    "assessment.importance debe ser low, medium, high o critical."
                )
            impact_direction = self._required_text(
                raw.impact_direction, "assessment.impact_direction"
            ).lower()
            if impact_direction not in _ALLOWED_IMPACT_DIRECTIONS:
                raise ValueError(
                    "assessment.impact_direction debe ser negative, neutral, positive, mixed o uncertain."
                )
            impact_magnitude = self._unit_interval(
                raw.impact_magnitude, "assessment.impact_magnitude"
            )
            confidence = self._unit_interval(raw.confidence, "assessment.confidence")

            assessment_fingerprint = self._assessment_fingerprint(
                evidence_fingerprint=expected_input_fingerprint,
                model_provider=model_provider,
                model_name=model_name,
                model_version=model_version,
                generated_at=generated_at,
                summary=summary,
                importance=importance,
                impact_direction=impact_direction,
                impact_magnitude=impact_magnitude,
                confidence=confidence,
            )
            if evidence.provider is None or evidence.publisher is None:
                raise ValueError(
                    "La evidencia news canónica debe conservar provider y publisher."
                )
            if evidence.published_at is None:
                raise ValueError(
                    "La evidencia news canónica debe conservar published_at."
                )
            validated.append(
                NewsSynthesisItem(
                    evidence_id=evidence_id,
                    instrument_id=instrument_id,
                    symbol=symbol,
                    source_ref=evidence.source_ref,
                    evidence_provider=evidence.provider,
                    publisher=evidence.publisher,
                    published_at=self._aware_utc(
                        evidence.published_at, "evidence.published_at"
                    ).isoformat(),
                    available_at=available_at.isoformat(),
                    model_provider=model_provider,
                    model_name=model_name,
                    model_version=model_version,
                    generated_at=generated_at.isoformat(),
                    input_fingerprint=expected_input_fingerprint,
                    assessment_fingerprint=assessment_fingerprint,
                    summary=summary,
                    importance=importance,
                    impact_direction=impact_direction,
                    impact_magnitude=impact_magnitude,
                    confidence=confidence,
                )
            )

        if seen_assessments != set(news_evidence):
            raise ValueError(
                "Las evaluaciones del modelo deben cubrir exactamente toda la evidencia news."
            )

        validated.sort(
            key=lambda item: (
                item.instrument_id.casefold(),
                item.symbol,
                item.evidence_id,
            )
        )
        included = [
            item
            for item in validated
            if _IMPORTANCE_ORDER[item.importance] >= _IMPORTANCE_ORDER[threshold]
        ]
        included.sort(
            key=lambda item: (
                -_IMPORTANCE_ORDER[item.importance],
                -item.impact_magnitude,
                item.instrument_id.casefold(),
                item.evidence_id,
            )
        )
        return NewsSynthesisResult(
            as_of=as_of.isoformat(),
            minimum_importance=threshold,
            assessed_count=len(validated),
            included_count=len(included),
            excluded_count=len(validated) - len(included),
            assessments=tuple(validated),
            items=tuple(included),
        )

    def evidence_fingerprint(
        self,
        *,
        instrument_id: str,
        symbol: str,
        evidence: AthenaRadarEvidenceInput,
    ) -> str:
        payload = {
            "instrumentId": self._required_text(instrument_id, "instrument_id"),
            "symbol": self._required_text(symbol, "symbol").upper(),
            "evidenceId": self._required_text(evidence.evidence_id, "evidence.evidence_id"),
            "category": self._required_text(evidence.category, "evidence.category").lower(),
            "urgency": self._required_text(evidence.urgency, "evidence.urgency").lower(),
            "source": self._required_text(evidence.source, "evidence.source"),
            "sourceRef": self._required_text(evidence.source_ref, "evidence.source_ref"),
            "provider": self._required_text(evidence.provider, "evidence.provider"),
            "publisher": self._required_text(evidence.publisher, "evidence.publisher"),
            "publishedAt": self._aware_utc(
                evidence.published_at, "evidence.published_at"
            ).isoformat(),
            "availableAt": self._aware_utc(
                evidence.available_at, "evidence.available_at"
            ).isoformat(),
            "sourceSummary": self._required_text(evidence.summary, "evidence.summary"),
        }
        return self._sha256(payload)

    def _canonical_radar(self, radar_result: AthenaRadarResult) -> AthenaRadarResult:
        if not isinstance(radar_result, AthenaRadarResult):
            raise ValueError("radar_result debe ser AthenaRadarResult.")
        try:
            as_of = datetime.fromisoformat(
                self._required_text(radar_result.as_of, "radar_result.as_of").replace(
                    "Z", "+00:00"
                )
            )
        except ValueError as exc:
            raise ValueError("radar_result.as_of debe ser ISO-8601 válido.") from exc
        candidates = tuple(
            AthenaRadarCandidateInput(
                instrument_id=candidate.instrument_id,
                symbol=candidate.symbol,
                evidence=tuple(candidate.evidence),
            )
            for candidate in radar_result.candidates
        )
        rebuilt = self._radar.build(as_of=as_of, candidates=candidates)
        if rebuilt != radar_result:
            raise ValueError(
                "radar_result no coincide con el resultado canónico de ATHENA Radar."
            )
        return rebuilt

    def _assessment_fingerprint(
        self,
        *,
        evidence_fingerprint: str,
        model_provider: str,
        model_name: str,
        model_version: str,
        generated_at: datetime,
        summary: str,
        importance: str,
        impact_direction: str,
        impact_magnitude: float,
        confidence: float,
    ) -> str:
        return self._sha256(
            {
                "inputFingerprint": evidence_fingerprint,
                "modelProvider": model_provider,
                "modelName": model_name,
                "modelVersion": model_version,
                "generatedAt": generated_at.isoformat(),
                "summary": summary,
                "importance": importance,
                "impactDirection": impact_direction,
                "impactMagnitude": impact_magnitude,
                "confidence": confidence,
            }
        )

    def _sha256(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _aware_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} debe ser datetime con timezone.")
        return value.astimezone(timezone.utc)

    def _unit_interval(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico entre 0 y 1.")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico entre 0 y 1.") from exc
        if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
            raise ValueError(f"{field} debe ser finito y estar entre 0 y 1.")
        return parsed

    def _assert_provider_allowed(self, provider: str) -> None:
        compact = "".join(ch for ch in provider.casefold() if ch.isalnum())
        if any(token in compact for token in _FORBIDDEN_SOURCE_TOKENS):
            raise ValueError(
                "Financial Modeling Prep (FMP) está prohibido como proveedor de síntesis."
            )
