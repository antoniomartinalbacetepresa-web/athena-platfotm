from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_ALLOWED_CATEGORIES = frozenset(
    {
        "expectations_gap",
        "reverse_valuation",
        "scenario_asymmetry",
        "catalysts",
        "thesis_invalidation",
        "factor_risk",
        "performance_attribution",
        "investment_journal",
        "devils_advocate",
        "news",
        "investors",
        "data_quality",
        "fx",
    }
)
_ALLOWED_URGENCIES = frozenset({"routine", "material", "critical"})
_URGENCY_ORDER = {"routine": 0, "material": 1, "critical": 2}


@dataclass(frozen=True)
class AthenaRadarEvidenceInput:
    evidence_id: str
    category: str
    urgency: str
    summary: str
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class AthenaRadarCandidateInput:
    instrument_id: str
    symbol: str
    evidence: tuple[AthenaRadarEvidenceInput, ...]


@dataclass(frozen=True)
class AthenaRadarCandidateResult:
    instrument_id: str
    symbol: str
    research_urgency: str
    evidence: tuple[AthenaRadarEvidenceInput, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "researchUrgency": self.research_urgency,
            "evidenceCount": len(self.evidence),
            "coveredCategories": sorted({item.category for item in self.evidence}),
            "evidence": [
                {
                    "evidenceId": item.evidence_id,
                    "category": item.category,
                    "urgency": item.urgency,
                    "summary": item.summary,
                    "availableAt": item.available_at.isoformat(),
                    "source": item.source,
                    "sourceRef": item.source_ref,
                }
                for item in self.evidence
            ],
        }


@dataclass(frozen=True)
class AthenaRadarResult:
    as_of: str
    candidates: tuple[AthenaRadarCandidateResult, ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "research_attention_queue_ready",
            "asOf": self.as_of,
            "mode": "research_attention_only",
            "rankingInterpretation": "research_urgency_not_investment_preference",
            "candidateCount": len(self.candidates),
            "candidates": [candidate.to_api_dict() for candidate in self.candidates],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "temporal": "all_radar_evidence_available_at_must_be_lte_as_of",
                "provenance": "every_radar_evidence_item_requires_source_and_source_ref",
                "identity": "canonical_candidate_and_evidence_identity_must_be_unique",
                "deduplication": "duplicate_provenance_cannot_raise_research_urgency_twice",
                "missingEvidence": "unknown_not_zero_or_benign_and_candidate_requires_explicit_evidence",
                "scoring": "no_numeric_score_without_independent_out_of_sample_calibration",
                "probability": "not_estimated",
                "expectedReturn": "not_estimated",
                "interpretation": "critical_means_research_urgency_only_not_expected_loss_or_investment_attractiveness",
                "fx": "explicit_evidence_only_no_implicit_fx_neutrality",
                "sourceSecurity": "fmp_and_financialmodelingprep_sources_forbidden",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationAthenaRadarService:
    """Build a deterministic PIT research-attention queue without investment ranking."""

    def build(
        self,
        *,
        as_of: datetime,
        candidates: tuple[AthenaRadarCandidateInput, ...],
    ) -> AthenaRadarResult:
        cutoff = self._aware_utc(as_of, "as_of")
        if not isinstance(candidates, tuple) or not candidates:
            raise ValueError("candidates debe contener al menos un instrumento con evidencia explícita.")
        if len(candidates) > 500:
            raise ValueError("candidates no puede contener más de 500 instrumentos.")

        seen_candidates: set[tuple[str, str]] = set()
        seen_evidence_ids: set[str] = set()
        seen_provenance: set[tuple[str, str]] = set()
        normalized_candidates: list[AthenaRadarCandidateResult] = []

        for raw_candidate in candidates:
            if not isinstance(raw_candidate, AthenaRadarCandidateInput):
                raise ValueError("Cada candidato debe ser AthenaRadarCandidateInput.")
            instrument_id = self._required_text(
                raw_candidate.instrument_id, "candidate.instrument_id"
            )
            symbol = self._required_text(raw_candidate.symbol, "candidate.symbol").upper()
            candidate_key = (instrument_id.casefold(), symbol)
            if candidate_key in seen_candidates:
                raise ValueError("La identidad canónica del candidato no puede repetirse.")
            seen_candidates.add(candidate_key)

            if not isinstance(raw_candidate.evidence, tuple) or not raw_candidate.evidence:
                raise ValueError(
                    "Cada candidato necesita evidencia explícita; ausencia de evidencia no equivale a riesgo cero."
                )
            if len(raw_candidate.evidence) > 200:
                raise ValueError("Un candidato no puede contener más de 200 evidencias.")

            normalized_evidence: list[AthenaRadarEvidenceInput] = []
            maximum_urgency = "routine"
            for raw_evidence in raw_candidate.evidence:
                if not isinstance(raw_evidence, AthenaRadarEvidenceInput):
                    raise ValueError("Cada evidencia debe ser AthenaRadarEvidenceInput.")
                evidence_id = self._required_text(
                    raw_evidence.evidence_id, "evidence.evidence_id"
                )
                if evidence_id in seen_evidence_ids:
                    raise ValueError("evidence_id debe ser único en toda la cola Radar.")
                seen_evidence_ids.add(evidence_id)

                category = self._required_text(raw_evidence.category, "evidence.category").lower()
                if category not in _ALLOWED_CATEGORIES:
                    raise ValueError("evidence.category no está soportada por ATHENA Radar.")
                urgency = self._required_text(raw_evidence.urgency, "evidence.urgency").lower()
                if urgency not in _ALLOWED_URGENCIES:
                    raise ValueError("evidence.urgency debe ser routine, material o critical.")
                summary = self._required_text(raw_evidence.summary, "evidence.summary")
                available_at = self._aware_utc(
                    raw_evidence.available_at, "evidence.available_at"
                )
                if available_at > cutoff:
                    raise ValueError(
                        "evidence.available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio."
                    )
                source = self._required_text(raw_evidence.source, "evidence.source")
                source_ref = self._required_text(raw_evidence.source_ref, "evidence.source_ref")
                self._assert_source_allowed(source, source_ref)

                provenance_key = (source.casefold(), source_ref.casefold())
                if provenance_key in seen_provenance:
                    raise ValueError(
                        "La misma provenance no puede reutilizarse para elevar dos veces la urgencia Radar."
                    )
                seen_provenance.add(provenance_key)

                normalized_evidence.append(
                    AthenaRadarEvidenceInput(
                        evidence_id=evidence_id,
                        category=category,
                        urgency=urgency,
                        summary=summary,
                        available_at=available_at,
                        source=source,
                        source_ref=source_ref,
                    )
                )
                if _URGENCY_ORDER[urgency] > _URGENCY_ORDER[maximum_urgency]:
                    maximum_urgency = urgency

            normalized_evidence.sort(key=lambda item: (item.category, item.evidence_id))
            normalized_candidates.append(
                AthenaRadarCandidateResult(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    research_urgency=maximum_urgency,
                    evidence=tuple(normalized_evidence),
                )
            )

        normalized_candidates.sort(
            key=lambda item: (
                -_URGENCY_ORDER[item.research_urgency],
                item.instrument_id.casefold(),
                item.symbol,
            )
        )
        return AthenaRadarResult(
            as_of=cutoff.isoformat(),
            candidates=tuple(normalized_candidates),
        )

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar semántica y provenance.")
        return text

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _assert_source_allowed(self, source: str, source_ref: str) -> None:
        normalized_source = source.casefold().replace(" ", "")
        normalized_ref = source_ref.casefold()
        if normalized_source == "fmp" or "financialmodelingprep" in normalized_source:
            raise ValueError("FMP/Financial Modeling Prep no está permitido como fuente de ATHENA Radar.")
        if "financialmodelingprep" in normalized_ref:
            raise ValueError("FMP/Financial Modeling Prep no está permitido como provenance de ATHENA Radar.")
