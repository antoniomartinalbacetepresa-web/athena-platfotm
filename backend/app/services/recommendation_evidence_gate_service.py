from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Protocol

from app.services.recommendation_fundamental_signal_service import (
    RecommendationFundamentalSignalService,
)
from app.services.recommendation_market_signal_service import (
    RecommendationMarketSignalService,
)
from app.services.recommendation_valuation_signal_service import (
    RecommendationValuationSignalService,
)


class _DiagnosticService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


@dataclass(frozen=True)
class RecommendationEvidenceGate:
    status: str
    symbol: str
    as_of: str
    instrument_id: int | None
    core_evidence_ready: bool
    market_evidence_ready: bool
    fundamental_evidence_ready: bool
    identity_consistent: bool
    provenance_contract_ready: bool
    valuation_ready: bool
    calibration_ready: bool
    recommendation_candidate_ready: bool
    blockers: tuple[str, ...]
    market: dict[str, Any]
    fundamentals: dict[str, Any]
    valuation: dict[str, Any]
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "asOf": self.as_of,
            "instrumentId": self.instrument_id,
            "coreEvidenceReady": self.core_evidence_ready,
            "marketEvidenceReady": self.market_evidence_ready,
            "fundamentalEvidenceReady": self.fundamental_evidence_ready,
            "identityConsistent": self.identity_consistent,
            "provenanceContractReady": self.provenance_contract_ready,
            "valuationReady": self.valuation_ready,
            "calibrationReady": self.calibration_ready,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "blockers": list(self.blockers),
            "market": self.market,
            "fundamentals": self.fundamentals,
            "valuation": self.valuation,
            "analysisCoverage": self._analysis_coverage(),
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "failClosed": True,
                "samePointInTimeCutoff": True,
                "sameInstrumentRequired": True,
                "componentDiagnosticsMustRemainNonProductive": True,
                "qualityThreshold": "not_assumed_until_empirically_calibrated",
                "valuation": "pit_reported_annual_pe_required_for_initial_gate",
                "calibration": "out_of_sample_validation_required",
                "investorActivity": (
                    "independent_parallel_evidence_not_part_of_athena_recommendation"
                ),
            },
        }

    def _analysis_coverage(self) -> dict[str, Any]:
        market_status = self.market.get("status")
        fundamental_status = self.fundamentals.get("status")
        valuation_status = self.valuation.get("status")
        return {
            "technical": {
                "connected": True,
                "influencesCandidate": True,
                "sourceBlock": "market",
                "status": market_status,
                "evidenceReady": self.market_evidence_ready,
                "productionEligible": False,
            },
            "risk": {
                "connected": True,
                "influencesCandidate": True,
                "sourceBlock": "market",
                "status": market_status,
                "evidenceReady": self.market_evidence_ready,
                "productionEligible": False,
            },
            "fundamentals": {
                "connected": True,
                "influencesCandidate": True,
                "sourceBlock": "fundamentals",
                "status": fundamental_status,
                "evidenceReady": self.fundamental_evidence_ready,
                "productionEligible": False,
            },
            "valuation": {
                "connected": True,
                "influencesCandidate": True,
                "sourceBlock": "valuation",
                "status": valuation_status,
                "evidenceReady": self.valuation_ready,
                "productionEligible": False,
            },
            "marketMacro": {
                "connected": False,
                "influencesCandidate": False,
                "status": "infrastructure_available_not_connected_to_candidate",
                "evidenceReady": False,
                "productionEligible": False,
            },
            "dataQuality": {
                "connected": False,
                "influencesCandidate": False,
                "status": "infrastructure_available_not_connected_to_candidate",
                "evidenceReady": False,
                "productionEligible": False,
            },
            "calibration": {
                "connected": True,
                "influencesCandidate": False,
                "status": (
                    "validated" if self.calibration_ready else "not_validated"
                ),
                "evidenceReady": self.calibration_ready,
                "productionEligible": False,
            },
            "recommendationCombination": {
                "connected": True,
                "influencesCandidate": False,
                "status": (
                    "candidate_ready"
                    if self.recommendation_candidate_ready
                    else "blocked_until_calibration"
                ),
                "evidenceReady": self.recommendation_candidate_ready,
                "productionEligible": False,
            },
            "investorActivity": {
                "connected": False,
                "influencesCandidate": False,
                "status": "independent_engine_not_yet_connected",
                "evidenceReady": False,
                "includedInAthenaRecommendation": False,
                "productionEligible": False,
            },
        }


class RecommendationEvidenceGateService:
    """Fail-closed gate over recommendation evidence available at one PIT cutoff."""

    def __init__(
        self,
        *,
        market_service: _DiagnosticService | None = None,
        fundamental_service: _DiagnosticService | None = None,
        valuation_service: _DiagnosticService | None = None,
    ) -> None:
        self._market_service = (
            market_service
            if market_service is not None
            else RecommendationMarketSignalService()
        )
        self._fundamental_service = (
            fundamental_service
            if fundamental_service is not None
            else RecommendationFundamentalSignalService()
        )
        self._valuation_service = (
            valuation_service
            if valuation_service is not None
            else RecommendationValuationSignalService()
        )

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
    ) -> RecommendationEvidenceGate:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)

        market_payload = self._safe_payload(
            self._market_service.evaluate(symbol=normalized_symbol, as_of=as_of_utc),
            component_name="market",
            expected_symbol=normalized_symbol,
            expected_as_of=as_of_utc,
        )
        fundamental_payload = self._safe_payload(
            self._fundamental_service.evaluate(
                symbol=normalized_symbol,
                as_of=as_of_utc,
            ),
            component_name="fundamentals",
            expected_symbol=normalized_symbol,
            expected_as_of=as_of_utc,
        )
        valuation_payload = self._safe_payload(
            self._valuation_service.evaluate(
                symbol=normalized_symbol,
                as_of=as_of_utc,
            ),
            component_name="valuation",
            expected_symbol=normalized_symbol,
            expected_as_of=as_of_utc,
        )

        market_ready = market_payload.get("status") == "diagnostic_ready"
        fundamental_ready = (
            fundamental_payload.get("status") == "diagnostic_ready"
            and self._float_at_least(fundamental_payload.get("coverageRatio"), 0.75)
        )
        valuation_ready = (
            valuation_payload.get("status") == "diagnostic_ready"
            and self._positive_float(valuation_payload.get("reportedAnnualPe"))
        )

        market_instrument_id = self._optional_int(market_payload.get("instrumentId"))
        fundamental_instrument_id = self._optional_int(
            fundamental_payload.get("instrumentId")
        )
        valuation_instrument_id = self._optional_int(
            valuation_payload.get("instrumentId")
        )
        identity_consistent = self._identity_consistent(
            market_instrument_id,
            fundamental_instrument_id,
            valuation_instrument_id,
        )
        instrument_id = market_instrument_id if identity_consistent else None

        provenance_contract_ready = self._provenance_contract_ready(
            market_payload=market_payload,
            fundamental_payload=fundamental_payload,
            valuation_payload=valuation_payload,
            valuation_ready=valuation_ready,
        )
        calibration_ready = False
        core_evidence_ready = (
            market_ready
            and fundamental_ready
            and identity_consistent
            and provenance_contract_ready
        )

        blockers: list[str] = []
        if not market_ready:
            blockers.append("market_evidence_not_ready")
        if not fundamental_ready:
            blockers.append("fundamental_evidence_not_ready")
        if not identity_consistent:
            blockers.append("instrument_identity_mismatch")
        if not provenance_contract_ready:
            blockers.append("provenance_contract_incomplete")
        if not valuation_ready:
            blockers.append("valuation_not_ready")
        if not calibration_ready:
            blockers.append("calibration_not_validated")

        recommendation_candidate_ready = (
            core_evidence_ready and valuation_ready and calibration_ready
        )
        if recommendation_candidate_ready:
            raise RuntimeError(
                "El evidence gate no puede habilitar candidatos todavía."
            )

        if core_evidence_ready and valuation_ready:
            status = "evidence_ready_for_calibration"
            reason = (
                "Mercado, fundamentales, identidad, procedencia y la valoración PIT "
                "inicial superan el gate de evidencia. ATHENA mantiene bloqueado el "
                "consejo hasta validar la combinación fuera de muestra."
            )
        elif core_evidence_ready:
            status = "core_evidence_ready"
            reason = (
                "La evidencia técnica/riesgo y fundamental supera el gate básico, "
                "pero la valoración PIT aún no está lista y no se genera consejo."
            )
        else:
            status = "evidence_incomplete"
            reason = (
                "La evidencia disponible no supera todavía el gate básico de ATHENA; "
                "los bloqueos se exponen explícitamente y no se genera consejo."
            )

        return RecommendationEvidenceGate(
            status=status,
            symbol=normalized_symbol,
            as_of=as_of_utc.isoformat(),
            instrument_id=instrument_id,
            core_evidence_ready=core_evidence_ready,
            market_evidence_ready=market_ready,
            fundamental_evidence_ready=fundamental_ready,
            identity_consistent=identity_consistent,
            provenance_contract_ready=provenance_contract_ready,
            valuation_ready=valuation_ready,
            calibration_ready=calibration_ready,
            recommendation_candidate_ready=recommendation_candidate_ready,
            blockers=tuple(blockers),
            market=market_payload,
            fundamentals=fundamental_payload,
            valuation=valuation_payload,
            production_eligible=False,
            reason=reason,
        )

    def _safe_payload(
        self,
        diagnostic: object,
        *,
        component_name: str,
        expected_symbol: str,
        expected_as_of: datetime,
    ) -> dict[str, Any]:
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError(
                f"El componente {component_name} no respeta el contrato diagnóstico."
            )
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"El componente {component_name} devolvió un contrato inválido."
            )
        if payload.get("productionEligible") is not False:
            raise RuntimeError(
                f"El componente {component_name} intentó declararse productivo."
            )
        if str(payload.get("symbol") or "").strip().upper() != expected_symbol:
            raise RuntimeError(
                f"El componente {component_name} devolvió otro símbolo."
            )
        component_as_of = self._parse_aware_datetime(payload.get("asOf"))
        if component_as_of != expected_as_of:
            raise RuntimeError(
                f"El componente {component_name} usó un corte point-in-time distinto."
            )
        return dict(payload)

    def _provenance_contract_ready(
        self,
        *,
        market_payload: dict[str, Any],
        fundamental_payload: dict[str, Any],
        valuation_payload: dict[str, Any],
        valuation_ready: bool,
    ) -> bool:
        market_sources = market_payload.get("sourceProviders")
        fundamental_facts = fundamental_payload.get("facts")
        has_market_sources = (
            isinstance(market_sources, list)
            and bool(market_sources)
            and all(str(item).strip() for item in market_sources)
        )
        has_fundamental_provenance = (
            isinstance(fundamental_facts, list)
            and bool(fundamental_facts)
            and all(
                isinstance(item, dict)
                and bool(str(item.get("metric") or "").strip())
                and bool(str(item.get("availableAt") or "").strip())
                for item in fundamental_facts
            )
        )
        if not valuation_ready:
            return has_market_sources and has_fundamental_provenance
        valuation_fact = valuation_payload.get("annualDilutedEps")
        has_valuation_provenance = (
            isinstance(valuation_fact, dict)
            and bool(str(valuation_fact.get("metric") or "").strip())
            and bool(str(valuation_fact.get("availableAt") or "").strip())
            and str(valuation_fact.get("sourceVersion") or "").upper().startswith("10-K|")
        )
        valuation_sources = valuation_payload.get("marketSourceProviders")
        has_valuation_market_sources = (
            isinstance(valuation_sources, list)
            and bool(valuation_sources)
            and all(str(item).strip() for item in valuation_sources)
        )
        return (
            has_market_sources
            and has_fundamental_provenance
            and has_valuation_provenance
            and has_valuation_market_sources
        )

    def _identity_consistent(self, *instrument_ids: int | None) -> bool:
        if any(value is None for value in instrument_ids):
            return False
        resolved = {int(value) for value in instrument_ids if value is not None}
        return len(resolved) == 1

    def _float_at_least(self, value: object, threshold: float) -> bool:
        if isinstance(value, bool):
            return False
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return isfinite(numeric_value) and numeric_value >= threshold

    def _positive_float(self, value: object) -> bool:
        if isinstance(value, bool):
            return False
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return isfinite(numeric_value) and numeric_value > 0

    def _optional_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_aware_datetime(self, value: object) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError("El diagnóstico no incluye asOf.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("El diagnóstico incluye un asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("El diagnóstico incluye un asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
