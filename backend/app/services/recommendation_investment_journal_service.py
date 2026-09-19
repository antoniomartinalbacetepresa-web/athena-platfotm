from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_REFERENCE_KINDS = frozenset(
    {
        "assumption",
        "expectations_gap",
        "reverse_valuation",
        "scenario_asymmetry",
        "catalyst",
        "thesis_invalidation",
        "factor_risk",
        "performance_attribution",
        "portfolio_context",
        "news_evidence",
        "investor_evidence",
    }
)


@dataclass(frozen=True)
class InvestmentJournalReferenceInput:
    reference_id: str
    kind: str
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class InvestmentJournalSnapshot:
    journal_id: str
    revision_id: str
    symbol: str
    recorded_at: str
    as_of: str
    thesis: str
    references: tuple[InvestmentJournalReferenceInput, ...]
    prior_snapshot_hash: str | None
    snapshot_hash: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "snapshot_ready",
            "journalId": self.journal_id,
            "revisionId": self.revision_id,
            "symbol": self.symbol,
            "recordedAt": self.recorded_at,
            "asOf": self.as_of,
            "thesis": self.thesis,
            "references": [
                {
                    "referenceId": item.reference_id,
                    "kind": item.kind,
                    "availableAt": item.available_at.isoformat(),
                    "source": item.source,
                    "sourceRef": item.source_ref,
                }
                for item in self.references
            ],
            "priorSnapshotHash": self.prior_snapshot_hash,
            "snapshotHash": self.snapshot_hash,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "temporal": "all_references_available_at_must_be_lte_recorded_at_lte_as_of",
                "provenance": "every_reference_requires_source_and_source_ref",
                "identity": "journal_revision_and_reference_ids_must_be_unique_within_snapshot",
                "immutability": "snapshot_hash_is_sha256_of_canonical_snapshot_payload",
                "revisionLineage": "prior_snapshot_hash_is_explicit_but_existence_not_verified_without_persistence",
                "hindsight": "snapshot_records_only_evidence_available_when_recorded",
                "interpretation": "research_journal_snapshot_not_advice_or_outcome_validation",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "persistentAppendOnlyStorage": False,
            },
        }


class RecommendationInvestmentJournalService:
    """Freeze a provenance-bound PIT research snapshot before outcomes are known.

    This first journal layer is deliberately storage-agnostic. It produces a
    canonical SHA-256 fingerprint suitable for later append-only persistence,
    but does not claim that the snapshot has already been durably stored.
    """

    def freeze_snapshot(
        self,
        *,
        journal_id: str,
        revision_id: str,
        symbol: str,
        recorded_at: datetime,
        as_of: datetime,
        thesis: str,
        references: tuple[InvestmentJournalReferenceInput, ...],
        prior_snapshot_hash: str | None = None,
    ) -> InvestmentJournalSnapshot:
        normalized_journal_id = self._required_text(journal_id, "journal_id")
        normalized_revision_id = self._required_text(revision_id, "revision_id")
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        normalized_thesis = self._required_text(thesis, "thesis")
        recorded = self._aware_utc(recorded_at, "recorded_at")
        cutoff = self._aware_utc(as_of, "as_of")
        if recorded > cutoff:
            raise ValueError("recorded_at no puede ser posterior a as_of; evitar look-ahead es obligatorio.")
        if not isinstance(references, tuple) or not references:
            raise ValueError("references debe contener al menos una referencia PIT explícita.")
        if len(references) > 200:
            raise ValueError("references no puede contener más de 200 elementos.")

        normalized_prior = None
        if prior_snapshot_hash is not None:
            normalized_prior = str(prior_snapshot_hash).strip().lower()
            if not _SHA256_RE.fullmatch(normalized_prior):
                raise ValueError("prior_snapshot_hash debe ser un SHA-256 hexadecimal de 64 caracteres.")

        seen_ids: set[str] = set()
        normalized_refs: list[InvestmentJournalReferenceInput] = []
        for raw in references:
            if not isinstance(raw, InvestmentJournalReferenceInput):
                raise ValueError("Cada referencia debe ser InvestmentJournalReferenceInput.")
            reference_id = self._required_text(raw.reference_id, "reference.reference_id")
            if reference_id in seen_ids:
                raise ValueError("reference_id no puede repetirse dentro del snapshot.")
            seen_ids.add(reference_id)
            kind = self._required_text(raw.kind, "reference.kind").lower()
            if kind not in _ALLOWED_REFERENCE_KINDS:
                raise ValueError("reference.kind no está soportado por Investment Journal.")
            available_at = self._aware_utc(raw.available_at, "reference.available_at")
            if available_at > recorded:
                raise ValueError("reference.available_at no puede ser posterior a recorded_at; evitar hindsight/look-ahead es obligatorio.")
            source = self._required_text(raw.source, "reference.source")
            source_ref = self._required_text(raw.source_ref, "reference.source_ref")
            normalized_refs.append(
                InvestmentJournalReferenceInput(
                    reference_id=reference_id,
                    kind=kind,
                    available_at=available_at,
                    source=source,
                    source_ref=source_ref,
                )
            )

        normalized_refs.sort(key=lambda item: (item.kind, item.reference_id))
        canonical = {
            "journalId": normalized_journal_id,
            "revisionId": normalized_revision_id,
            "symbol": normalized_symbol,
            "recordedAt": recorded.isoformat(),
            "asOf": cutoff.isoformat(),
            "thesis": normalized_thesis,
            "priorSnapshotHash": normalized_prior,
            "references": [
                {
                    "referenceId": item.reference_id,
                    "kind": item.kind,
                    "availableAt": item.available_at.isoformat(),
                    "source": item.source,
                    "sourceRef": item.source_ref,
                }
                for item in normalized_refs
            ],
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        snapshot_hash = hashlib.sha256(encoded).hexdigest()
        return InvestmentJournalSnapshot(
            journal_id=normalized_journal_id,
            revision_id=normalized_revision_id,
            symbol=normalized_symbol,
            recorded_at=recorded.isoformat(),
            as_of=cutoff.isoformat(),
            thesis=normalized_thesis,
            references=tuple(normalized_refs),
            prior_snapshot_hash=normalized_prior,
            snapshot_hash=snapshot_hash,
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
