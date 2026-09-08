from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.recommendation_athena_radar_service import AthenaRadarResult
from app.services.recommendation_devils_advocate_service import DevilsAdvocateResult
from app.services.recommendation_investment_journal_service import InvestmentJournalSnapshot


_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


@dataclass(frozen=True)
class ProfessionalResearchCycleResult:
    instrument_id: str
    symbol: str
    as_of: str
    research_urgency: str
    journal_id: str
    revision_id: str
    snapshot_hash: str
    contradictory_evidence_count: int
    fx_evidence_status: str
    radar_hash: str
    devils_advocate_hash: str
    cycle_hash: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "professional_research_cycle_ready_for_human_review",
            "mode": "research_only",
            "instrumentId": self.instrument_id,
            "symbol": self.symbol,
            "asOf": self.as_of,
            "researchUrgency": self.research_urgency,
            "researchUrgencyInterpretation": "attention_priority_not_investment_preference",
            "journal": {
                "journalId": self.journal_id,
                "revisionId": self.revision_id,
                "snapshotHash": self.snapshot_hash,
                "snapshotBindingVerified": True,
            },
            "devilsAdvocate": {
                "contradictoryEvidenceCount": self.contradictory_evidence_count,
                "interpretation": "contradictory_evidence_not_sell_signal_or_proof_thesis_is_false",
            },
            "fxEvidenceStatus": self.fx_evidence_status,
            "integrity": {
                "algorithm": "sha256",
                "radarHash": self.radar_hash,
                "journalSnapshotHash": self.snapshot_hash,
                "devilsAdvocateHash": self.devils_advocate_hash,
                "cycleHash": self.cycle_hash,
                "scope": "canonical_full_module_payloads_plus_exact_cycle_identity",
            },
            "humanReviewRequired": True,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "temporal": "radar_journal_and_devils_advocate_share_exact_pit_as_of",
                "journalBinding": "devils_advocate_must_match_exact_journal_revision_and_snapshot_hash",
                "identity": "instrument_and_symbol_must_match_across_the_research_cycle",
                "provenance": "all_underlying_module_evidence_keeps_explicit_source_and_source_ref",
                "fx": "explicit_or_unknown_never_implicitly_neutral",
                "sourceSecurity": "fmp_and_financialmodelingprep_sources_forbidden_across_cycle",
                "scoring": "research_urgency_is_not_expected_return_probability_or_recommendation_score",
                "tamperEvidence": "cycle_hash_binds_canonical_radar_journal_and_devils_advocate_artifacts",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }


class RecommendationProfessionalResearchCycleService:
    """Bind Radar -> frozen Journal -> Devil's Advocate into one research-only PIT cycle.

    This service deliberately does not create an investment recommendation. It
    verifies that the three existing research artifacts refer to the same
    identity, point-in-time cutoff and exact journal snapshot before a human can
    review them together. The returned SHA-256 fingerprints make the exact
    research package tamper-evident without implying durable or WORM storage.
    """

    def bind(
        self,
        *,
        instrument_id: str,
        radar: AthenaRadarResult,
        journal: InvestmentJournalSnapshot,
        devils_advocate: DevilsAdvocateResult,
    ) -> ProfessionalResearchCycleResult:
        normalized_instrument_id = self._required_text(instrument_id, "instrument_id")
        if not isinstance(radar, AthenaRadarResult):
            raise ValueError("radar debe ser un AthenaRadarResult validado.")
        if not isinstance(journal, InvestmentJournalSnapshot):
            raise ValueError("journal debe ser un InvestmentJournalSnapshot validado.")
        if not isinstance(devils_advocate, DevilsAdvocateResult):
            raise ValueError("devils_advocate debe ser un DevilsAdvocateResult validado.")
        if len(radar.candidates) != 1:
            raise ValueError("El ciclo profesional debe enlazar exactamente un candidato Radar.")

        radar_payload = radar.to_api_dict()
        journal_payload = journal.to_api_dict()
        devils_payload = devils_advocate.to_api_dict()
        self._assert_safe_contract(radar_payload, "ATHENA Radar")
        self._assert_safe_contract(journal_payload, "Investment Journal")
        self._assert_safe_contract(devils_payload, "Devil's Advocate")

        candidate = radar.candidates[0]
        symbol = self._required_text(candidate.symbol, "radar.symbol").upper()
        if self._required_text(candidate.instrument_id, "radar.instrument_id") != normalized_instrument_id:
            raise ValueError("instrument_id no coincide con la identidad del candidato Radar.")
        if journal.symbol.upper() != symbol or devils_advocate.symbol.upper() != symbol:
            raise ValueError("El símbolo debe coincidir en Radar, Journal y Devil's Advocate.")
        if devils_advocate.journal_id != journal.journal_id:
            raise ValueError("Devil's Advocate no está vinculado al journal_id exacto del snapshot.")
        if devils_advocate.revision_id != journal.revision_id:
            raise ValueError("Devil's Advocate no está vinculado al revision_id exacto del snapshot.")
        if devils_advocate.snapshot_hash != journal.snapshot_hash:
            raise ValueError("Devil's Advocate no está vinculado al snapshot_hash exacto del Journal.")

        radar_as_of = self._aware_iso(radar.as_of, "radar.as_of")
        journal_as_of = self._aware_iso(journal.as_of, "journal.as_of")
        devil_as_of = self._aware_iso(devils_advocate.as_of, "devils_advocate.as_of")
        if radar_as_of != journal_as_of or radar_as_of != devil_as_of:
            raise ValueError("Radar, Journal y Devil's Advocate deben compartir el mismo as_of PIT exacto.")

        self._assert_no_forbidden_sources(radar_payload)
        self._assert_no_forbidden_sources(journal_payload)
        self._assert_no_forbidden_sources(devils_payload)

        fx_evidence = any(item.category == "fx" for item in candidate.evidence)
        radar_hash = self._canonical_hash(radar_payload)
        devils_advocate_hash = self._canonical_hash(devils_payload)
        cycle_hash = self._canonical_hash(
            {
                "instrumentId": normalized_instrument_id,
                "symbol": symbol,
                "asOf": radar_as_of.isoformat(),
                "journalId": journal.journal_id,
                "revisionId": journal.revision_id,
                "radarHash": radar_hash,
                "journalSnapshotHash": journal.snapshot_hash,
                "devilsAdvocateHash": devils_advocate_hash,
            }
        )

        return ProfessionalResearchCycleResult(
            instrument_id=normalized_instrument_id,
            symbol=symbol,
            as_of=radar_as_of.isoformat(),
            research_urgency=candidate.research_urgency,
            journal_id=journal.journal_id,
            revision_id=journal.revision_id,
            snapshot_hash=journal.snapshot_hash,
            contradictory_evidence_count=len(devils_advocate.evidence),
            fx_evidence_status="explicit" if fx_evidence else "unknown_not_neutral",
            radar_hash=radar_hash,
            devils_advocate_hash=devils_advocate_hash,
            cycle_hash=cycle_hash,
        )

    def _assert_safe_contract(self, payload: dict[str, Any], module: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{module} perdió advisoryStatus=no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{module} intentó habilitar producción.")
        if payload.get("isWeightingReady") is not False:
            raise ValueError(f"{module} intentó habilitar ponderación.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError(f"{module} perdió su política de seguridad.")
        if policy.get("automaticTrading") is not False:
            raise ValueError(f"{module} intentó habilitar trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError(f"{module} intentó promover producción automáticamente.")

    def _assert_no_forbidden_sources(self, payload: object) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"source", "sourceRef"} and isinstance(value, str):
                    normalized = value.casefold().replace("_", " ").replace("-", " ")
                    compact = normalized.replace(" ", "")
                    if "fmp" == compact or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
                        raise ValueError("FMP/Financial Modeling Prep está prohibido en el ciclo profesional.")
                self._assert_no_forbidden_sources(value)
        elif isinstance(payload, list):
            for value in payload:
                self._assert_no_forbidden_sources(value)

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _aware_iso(self, value: object, field: str) -> datetime:
        text = self._required_text(value, field)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser un datetime ISO válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed
