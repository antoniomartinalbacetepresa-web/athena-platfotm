from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_ALLOWED_KINDS = frozenset(
    {
        "valuation_risk",
        "expectations_risk",
        "scenario_downside",
        "catalyst_risk",
        "thesis_invalidation",
        "factor_risk",
        "news_evidence",
        "investor_evidence",
        "performance_attribution",
        "alternative_explanation",
        "data_quality",
    }
)
_ALLOWED_STRENGTHS = frozenset({"weak", "material", "critical"})


@dataclass(frozen=True)
class DevilsAdvocateEvidenceInput:
    evidence_id: str
    kind: str
    claim: str
    strength: str
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class DevilsAdvocateResult:
    journal_id: str
    revision_id: str
    snapshot_hash: str
    symbol: str
    as_of: str
    evidence: tuple[DevilsAdvocateEvidenceInput, ...]

    def to_api_dict(self) -> dict[str, Any]:
        counts = {strength: 0 for strength in sorted(_ALLOWED_STRENGTHS)}
        for item in self.evidence:
            counts[item.strength] += 1
        kinds = sorted({item.kind for item in self.evidence})
        return {
            "status": "contradictory_evidence_review_ready",
            "journalId": self.journal_id,
            "revisionId": self.revision_id,
            "snapshotHash": self.snapshot_hash,
            "symbol": self.symbol,
            "asOf": self.as_of,
            "evidenceCount": len(self.evidence),
            "strengthCounts": counts,
            "coveredKinds": kinds,
            "evidence": [
                {
                    "evidenceId": item.evidence_id,
                    "kind": item.kind,
                    "claim": item.claim,
                    "strength": item.strength,
                    "availableAt": item.available_at.isoformat(),
                    "source": item.source,
                    "sourceRef": item.source_ref,
                }
                for item in self.evidence
            ],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "temporal": "all_contradictory_evidence_available_at_must_be_lte_as_of",
                "provenance": "every_objection_requires_source_and_source_ref",
                "identity": "duplicate_evidence_ids_forbidden",
                "fabrication": "only_explicit_caller_supplied_evidence_is_reviewed_no_objections_are_invented",
                "scoring": "no_numeric_score_or_probability_without_independent_calibration",
                "interpretation": "contradictory_evidence_review_not_sell_signal_or_proof_thesis_is_false",
                "journalBinding": "review_is_bound_to_explicit_journal_revision_and_snapshot_hash",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationDevilsAdvocateService:
    """Review explicit PIT contradictory evidence against a frozen journal thesis."""

    def review(
        self,
        *,
        journal_id: str,
        revision_id: str,
        snapshot_hash: str,
        symbol: str,
        as_of: datetime,
        evidence: tuple[DevilsAdvocateEvidenceInput, ...],
    ) -> DevilsAdvocateResult:
        journal = self._required_text(journal_id, "journal_id")
        revision = self._required_text(revision_id, "revision_id")
        snapshot = self._required_text(snapshot_hash, "snapshot_hash").lower()
        if len(snapshot) != 64 or any(ch not in "0123456789abcdef" for ch in snapshot):
            raise ValueError("snapshot_hash debe ser un SHA-256 hexadecimal de 64 caracteres.")
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        cutoff = self._aware_utc(as_of, "as_of")
        if not isinstance(evidence, tuple) or not evidence:
            raise ValueError("evidence debe contener al menos una evidencia contradictoria explícita.")
        if len(evidence) > 200:
            raise ValueError("evidence no puede contener más de 200 elementos.")

        seen_ids: set[str] = set()
        normalized: list[DevilsAdvocateEvidenceInput] = []
        for raw in evidence:
            if not isinstance(raw, DevilsAdvocateEvidenceInput):
                raise ValueError("Cada evidencia debe ser DevilsAdvocateEvidenceInput.")
            evidence_id = self._required_text(raw.evidence_id, "evidence.evidence_id")
            if evidence_id in seen_ids:
                raise ValueError("evidence_id no puede repetirse.")
            seen_ids.add(evidence_id)
            kind = self._required_text(raw.kind, "evidence.kind").lower()
            if kind not in _ALLOWED_KINDS:
                raise ValueError("evidence.kind no está soportado por Devil's Advocate.")
            strength = self._required_text(raw.strength, "evidence.strength").lower()
            if strength not in _ALLOWED_STRENGTHS:
                raise ValueError("evidence.strength debe ser weak, material o critical.")
            claim = self._required_text(raw.claim, "evidence.claim")
            available_at = self._aware_utc(raw.available_at, "evidence.available_at")
            if available_at > cutoff:
                raise ValueError("evidence.available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio.")
            normalized.append(
                DevilsAdvocateEvidenceInput(
                    evidence_id=evidence_id,
                    kind=kind,
                    claim=claim,
                    strength=strength,
                    available_at=available_at,
                    source=self._required_text(raw.source, "evidence.source"),
                    source_ref=self._required_text(raw.source_ref, "evidence.source_ref"),
                )
            )

        normalized.sort(key=lambda item: (item.kind, item.evidence_id))
        return DevilsAdvocateResult(
            journal_id=journal,
            revision_id=revision,
            snapshot_hash=snapshot,
            symbol=normalized_symbol,
            as_of=cutoff.isoformat(),
            evidence=tuple(normalized),
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
