from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarResult,
    RecommendationAthenaRadarService,
)


_ALLOWED_IMPORTANCE = {"low", "medium", "high", "critical"}
_ALLOWED_DIRECTIONS = {"negative", "neutral", "positive", "mixed", "uncertain"}
_FORBIDDEN_PROVIDER_TOKENS = ("financialmodelingprep", "fmp")


@dataclass(frozen=True)
class InvestorsModelAssessmentInput:
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
class InvestorsSynthesisResult:
    as_of: str
    assessments: tuple[dict[str, Any], ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "validated_external_investors_model_output",
            "asOf": self.as_of,
            "assessedCount": len(self.assessments),
            "assessments": list(self.assessments),
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


class RecommendationInvestorsSynthesisService:
    """Bind external Investors/IR/filing assessments to exact PIT Radar evidence."""

    def __init__(self) -> None:
        self._radar = RecommendationAthenaRadarService()

    def build(
        self,
        *,
        radar_result: AthenaRadarResult,
        assessments: tuple[InvestorsModelAssessmentInput, ...],
    ) -> InvestorsSynthesisResult:
        canonical_radar = self._canonical_radar(radar_result)
        as_of = self._parse_iso(canonical_radar.as_of, "radar_result.as_of")
        investors: dict[str, tuple[str, str, Any]] = {}
        for candidate in canonical_radar.candidates:
            for evidence in candidate.evidence:
                if evidence.category == "investors":
                    investors[evidence.evidence_id] = (
                        candidate.instrument_id,
                        candidate.symbol,
                        evidence,
                    )
        if not investors:
            raise ValueError("Investors synthesis requiere evidencia investors canónica.")
        if not isinstance(assessments, tuple) or len(assessments) != len(investors):
            raise ValueError("Debe existir exactamente una evaluación por evidencia investors.")

        seen: set[str] = set()
        validated: list[dict[str, Any]] = []
        for raw in assessments:
            if not isinstance(raw, InvestorsModelAssessmentInput):
                raise ValueError("Cada assessment debe ser InvestorsModelAssessmentInput.")
            evidence_id = self._text(raw.evidence_id, "assessment.evidence_id")
            if evidence_id in seen:
                raise ValueError("assessment.evidence_id no puede repetirse.")
            seen.add(evidence_id)
            matched = investors.get(evidence_id)
            if matched is None:
                raise ValueError("assessment.evidence_id no corresponde a evidencia investors canónica.")
            instrument_id, symbol, evidence = matched
            if evidence.provider is None or evidence.publisher is None or evidence.published_at is None:
                raise ValueError("La evidencia investors debe conservar provider, primary source y published_at.")
            expected = self.evidence_fingerprint(
                instrument_id=instrument_id,
                symbol=symbol,
                evidence=evidence,
            )
            supplied = self._sha256_text(raw.input_fingerprint, "assessment.input_fingerprint")
            if supplied != expected:
                raise ValueError("assessment.input_fingerprint no coincide con evidencia investors canónica.")
            provider = self._text(raw.model_provider, "assessment.model_provider")
            self._assert_provider_allowed(provider)
            model_name = self._text(raw.model_name, "assessment.model_name")
            model_version = self._text(raw.model_version, "assessment.model_version")
            generated_at = self._aware(raw.generated_at, "assessment.generated_at")
            available_at = self._aware(evidence.available_at, "evidence.available_at")
            if generated_at < available_at or generated_at > as_of:
                raise ValueError("assessment.generated_at debe estar entre available_at y asOf.")
            importance = self._text(raw.importance, "assessment.importance").lower()
            if importance not in _ALLOWED_IMPORTANCE:
                raise ValueError("assessment.importance no está soportada.")
            direction = self._text(raw.impact_direction, "assessment.impact_direction").lower()
            if direction not in _ALLOWED_DIRECTIONS:
                raise ValueError("assessment.impact_direction no está soportada.")
            magnitude = self._unit(raw.impact_magnitude, "assessment.impact_magnitude")
            confidence = self._unit(raw.confidence, "assessment.confidence")
            summary = self._text(raw.summary, "assessment.summary")
            if len(summary) > 4000:
                raise ValueError("assessment.summary no puede superar 4000 caracteres.")
            assessment_fingerprint = self._hash({
                "inputFingerprint": expected,
                "modelProvider": provider,
                "modelName": model_name,
                "modelVersion": model_version,
                "generatedAt": generated_at.isoformat(),
                "summary": summary,
                "importance": importance,
                "impactDirection": direction,
                "impactMagnitude": magnitude,
                "confidence": confidence,
            })
            validated.append({
                "evidenceId": evidence_id,
                "instrumentId": instrument_id,
                "symbol": symbol,
                "sourceRef": evidence.source_ref,
                "evidenceProvider": evidence.provider,
                "primarySource": evidence.publisher,
                "publishedAt": self._aware(evidence.published_at, "evidence.published_at").isoformat(),
                "availableAt": available_at.isoformat(),
                "modelProvider": provider,
                "modelName": model_name,
                "modelVersion": model_version,
                "generatedAt": generated_at.isoformat(),
                "inputFingerprint": expected,
                "assessmentFingerprint": assessment_fingerprint,
                "summary": summary,
                "importance": importance,
                "impactDirection": direction,
                "impactMagnitude": magnitude,
                "confidence": confidence,
            })
        if seen != set(investors):
            raise ValueError("Las evaluaciones deben cubrir exactamente toda la evidencia investors.")
        validated.sort(key=lambda item: (item["instrumentId"].casefold(), item["evidenceId"]))
        return InvestorsSynthesisResult(as_of=as_of.isoformat(), assessments=tuple(validated))

    def evidence_fingerprint(self, *, instrument_id: str, symbol: str, evidence: Any) -> str:
        return self._hash({
            "instrumentId": self._text(instrument_id, "instrument_id"),
            "symbol": self._text(symbol, "symbol").upper(),
            "evidenceId": self._text(evidence.evidence_id, "evidence.evidence_id"),
            "category": self._text(evidence.category, "evidence.category").lower(),
            "urgency": self._text(evidence.urgency, "evidence.urgency").lower(),
            "source": self._text(evidence.source, "evidence.source"),
            "sourceRef": self._text(evidence.source_ref, "evidence.source_ref"),
            "provider": self._text(evidence.provider, "evidence.provider"),
            "primarySource": self._text(evidence.publisher, "evidence.publisher"),
            "publishedAt": self._aware(evidence.published_at, "evidence.published_at").isoformat(),
            "availableAt": self._aware(evidence.available_at, "evidence.available_at").isoformat(),
            "sourceSummary": self._text(evidence.summary, "evidence.summary"),
        })

    def _canonical_radar(self, radar_result: AthenaRadarResult) -> AthenaRadarResult:
        if not isinstance(radar_result, AthenaRadarResult):
            raise ValueError("radar_result debe ser AthenaRadarResult.")
        rebuilt = self._radar.build(
            as_of=self._parse_iso(radar_result.as_of, "radar_result.as_of"),
            candidates=tuple(
                AthenaRadarCandidateInput(
                    instrument_id=candidate.instrument_id,
                    symbol=candidate.symbol,
                    evidence=candidate.evidence,
                )
                for candidate in radar_result.candidates
            ),
        )
        if rebuilt != radar_result:
            raise ValueError(
                "radar_result debe coincidir exactamente con ATHENA Radar canónico; resultados fabricados o manipulados están prohibidos."
            )
        return rebuilt

    def _hash(self, payload: object) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

    def _sha256_text(self, value: object, field: str) -> str:
        text = self._text(value, field).lower()
        if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _aware(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir timezone.")
        return value.astimezone(timezone.utc)

    def _parse_iso(self, value: object, field: str) -> datetime:
        try:
            return self._aware(datetime.fromisoformat(self._text(value, field).replace("Z", "+00:00")), field)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc

    def _unit(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe estar entre 0 y 1.") from exc
        if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
            raise ValueError(f"{field} debe estar entre 0 y 1.")
        return parsed

    def _assert_provider_allowed(self, provider: str) -> None:
        compact = "".join(ch for ch in provider.casefold() if ch.isalnum())
        if any(token in compact for token in _FORBIDDEN_PROVIDER_TOKENS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido en Investors synthesis.")
