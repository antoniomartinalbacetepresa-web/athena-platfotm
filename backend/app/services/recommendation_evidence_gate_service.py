from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Protocol

from app.services.recommendation_fundamental_signal_service import (
    RecommendationFundamentalSignalService,
)
from app.services.recommendation_macro_evidence_service import (
    RecommendationMacroEvidenceService,
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
    data_quality_ready: bool
    valuation_ready: bool
    macro_context_ready: bool
    macro_context_valid: bool
    calibration_ready: bool
    recommendation_candidate_ready: bool
    blockers: tuple[str, ...]
    market: dict[str, Any]
    fundamentals: dict[str, Any]
    valuation: dict[str, Any]
    macro: dict[str, Any]
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
            "dataQualityReady": self.data_quality_ready,
            "valuationReady": self.valuation_ready,
            "macroContextReady": self.macro_context_ready,
            "macroContextValid": self.macro_context_valid,
            "calibrationReady": self.calibration_ready,
            "recommendationCandidateReady": self.recommendation_candidate_ready,
            "blockers": list(self.blockers),
            "market": self.market,
            "fundamentals": self.fundamentals,
            "valuation": self.valuation,
            "macro": self.macro,
            "analysisCoverage": self._analysis_coverage(),
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "failClosed": True,
                "samePointInTimeCutoff": True,
                "sameInstrumentRequired": True,
                "componentDiagnosticsMustRemainNonProductive": True,
                "qualityThreshold": "not_assumed_until_empirically_calibrated",
                "dataQuality": (
                    "structural_finiteness_and_pit_contract_only_no_empirical_"
                    "quality_threshold_assumed"
                ),
                "macro": (
                    "persisted_pit_context_captured_for_future_out_of_sample_"
                    "calibration_no_direction_or_weight_assumed"
                ),
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
        macro_status = self.macro.get("status")
        macro_connected = macro_status == "diagnostic_ready"
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
            "marketMacro": (
                {
                    "connected": True,
                    "influencesCandidate": False,
                    "sourceBlock": "macro",
                    "status": macro_status,
                    "evidenceReady": self.macro_context_ready,
                    "capturedForCalibration": True,
                    "directionalScoreAssigned": False,
                    "thresholdCalibrated": False,
                    "productionEligible": False,
                }
                if macro_connected
                else {
                    "connected": False,
                    "influencesCandidate": False,
                    "status": "infrastructure_available_not_connected_to_candidate",
                    "evidenceReady": False,
                    "productionEligible": False,
                }
            ),
            "dataQuality": {
                "connected": True,
                "influencesCandidate": True,
                "status": (
                    "structural_contract_ready"
                    if self.data_quality_ready
                    else "structural_contract_incomplete"
                ),
                "evidenceReady": self.data_quality_ready,
                "thresholdCalibrated": False,
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

    _MARKET_MIN_OBSERVATIONS = 61

    def __init__(
        self,
        *,
        market_service: _DiagnosticService | None = None,
        fundamental_service: _DiagnosticService | None = None,
        valuation_service: _DiagnosticService | None = None,
        macro_service: _DiagnosticService | None = None,
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
        self._macro_service = (
            macro_service
            if macro_service is not None
            else RecommendationMacroEvidenceService()
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
        macro_payload = self._safe_payload(
            self._macro_service.evaluate(
                symbol=normalized_symbol,
                as_of=as_of_utc,
            ),
            component_name="macro",
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
        macro_status = str(macro_payload.get("status") or "")
        macro_context_ready = (
            macro_status == "diagnostic_ready"
            and self._macro_context_contract_ready(macro_payload, as_of=as_of_utc)
        )
        macro_context_valid = macro_status == "no_data" or macro_context_ready

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
        data_quality_ready = self._data_quality_contract_ready(
            market_payload=market_payload,
            fundamental_payload=fundamental_payload,
            valuation_payload=valuation_payload,
            as_of=as_of_utc,
            market_ready=market_ready,
            fundamental_ready=fundamental_ready,
            valuation_ready=valuation_ready,
        )
        calibration_ready = False
        core_evidence_ready = (
            market_ready
            and fundamental_ready
            and identity_consistent
            and provenance_contract_ready
            and data_quality_ready
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
        if not data_quality_ready:
            blockers.append("data_quality_contract_incomplete")
        if not valuation_ready:
            blockers.append("valuation_not_ready")
        if not macro_context_valid:
            blockers.append("macro_context_invalid")
        if not calibration_ready:
            blockers.append("calibration_not_validated")

        recommendation_candidate_ready = (
            core_evidence_ready
            and valuation_ready
            and macro_context_valid
            and calibration_ready
        )
        if recommendation_candidate_ready:
            raise RuntimeError(
                "El evidence gate no puede habilitar candidatos todavía."
            )

        if core_evidence_ready and valuation_ready:
            status = "evidence_ready_for_calibration"
            reason = (
                "Mercado, fundamentales, identidad, procedencia, calidad estructural "
                "y valoración PIT superan el gate de evidencia. El contexto macro PIT "
                "se conserva cuando existe, sin dirección ni peso, y ATHENA mantiene "
                "bloqueado el consejo hasta validar la combinación fuera de muestra."
            )
        elif core_evidence_ready:
            status = "core_evidence_ready"
            reason = (
                "La evidencia técnica/riesgo y fundamental supera el gate básico de "
                "identidad, procedencia y calidad estructural, pero la valoración PIT "
                "aún no está lista y no se genera consejo."
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
            data_quality_ready=data_quality_ready,
            valuation_ready=valuation_ready,
            macro_context_ready=macro_context_ready,
            macro_context_valid=macro_context_valid,
            calibration_ready=calibration_ready,
            recommendation_candidate_ready=recommendation_candidate_ready,
            blockers=tuple(blockers),
            market=market_payload,
            fundamentals=fundamental_payload,
            valuation=valuation_payload,
            macro=macro_payload,
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

    def _macro_context_contract_ready(
        self,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> bool:
        observations = payload.get("observations")
        observation_count = self._optional_int(payload.get("observationCount"))
        if (
            observation_count is None
            or observation_count <= 0
            or not isinstance(observations, list)
            or len(observations) != observation_count
        ):
            return False
        for observation in observations:
            if not isinstance(observation, dict):
                return False
            if not str(observation.get("metric") or "").startswith("macro."):
                return False
            if not str(observation.get("sourceId") or "").strip():
                return False
            if not self._finite_float(observation.get("value")):
                return False
            available_at = self._optional_aware_datetime(
                observation.get("availableAt")
            )
            retrieved_at = self._optional_aware_datetime(
                observation.get("retrievedAt")
            )
            if (
                available_at is None
                or retrieved_at is None
                or available_at > as_of
                or retrieved_at > as_of
            ):
                return False
            for key in ("qualityScore", "confidenceScore"):
                score = observation.get(key)
                if score is not None and not self._float_between(score, 0.0, 100.0):
                    return False
        return True

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

    def _data_quality_contract_ready(
        self,
        *,
        market_payload: dict[str, Any],
        fundamental_payload: dict[str, Any],
        valuation_payload: dict[str, Any],
        as_of: datetime,
        market_ready: bool,
        fundamental_ready: bool,
        valuation_ready: bool,
    ) -> bool:
        if market_ready and not self._market_quality_ready(market_payload, as_of=as_of):
            return False
        if fundamental_ready and not self._fundamental_quality_ready(
            fundamental_payload,
            as_of=as_of,
        ):
            return False
        if valuation_ready and not self._valuation_quality_ready(
            valuation_payload,
            as_of=as_of,
        ):
            return False
        return market_ready and fundamental_ready

    def _market_quality_ready(
        self,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> bool:
        observation_count = self._optional_int(payload.get("observationCount"))
        if observation_count is None or observation_count < self._MARKET_MIN_OBSERVATIONS:
            return False
        if not self._positive_float(payload.get("latestPrice")):
            return False
        for key in ("return20d", "return60d", "maxDrawdown60d"):
            if not self._finite_float(payload.get(key)):
                return False
        if not self._non_negative_float(payload.get("annualizedVolatility")):
            return False
        for key in ("technicalScore", "riskScore"):
            if not self._float_between(payload.get(key), 0.0, 100.0):
                return False
        return self._pit_timestamp_pair_ready(
            observed_value=payload.get("latestObservedAt"),
            retrieved_value=payload.get("latestRetrievedAt"),
            as_of=as_of,
        )

    def _fundamental_quality_ready(
        self,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> bool:
        facts = payload.get("facts")
        if not isinstance(facts, list) or not facts:
            return False
        for fact in facts:
            if not isinstance(fact, dict):
                return False
            if not self._finite_float(fact.get("value")):
                return False
            available_at = self._optional_aware_datetime(fact.get("availableAt"))
            if available_at is None or available_at > as_of:
                return False
            quality_score = fact.get("qualityScore")
            if quality_score is not None and not self._finite_float(quality_score):
                return False
        for key in ("revenueGrowth", "netMargin", "liabilitiesToAssets"):
            value = payload.get(key)
            if value is not None and not self._finite_float(value):
                return False
        mean_quality_score = payload.get("meanQualityScore")
        if mean_quality_score is not None and not self._finite_float(mean_quality_score):
            return False
        return True

    def _valuation_quality_ready(
        self,
        payload: dict[str, Any],
        *,
        as_of: datetime,
    ) -> bool:
        if not self._positive_float(payload.get("latestPrice")):
            return False
        if not self._positive_float(payload.get("reportedAnnualPe")):
            return False
        if not self._pit_timestamp_pair_ready(
            observed_value=payload.get("latestPriceObservedAt"),
            retrieved_value=payload.get("latestPriceRetrievedAt"),
            as_of=as_of,
        ):
            return False
        eps = payload.get("annualDilutedEps")
        if not isinstance(eps, dict) or not self._positive_float(eps.get("value")):
            return False
        available_at = self._optional_aware_datetime(eps.get("availableAt"))
        if available_at is None or available_at > as_of:
            return False
        quality_score = eps.get("qualityScore")
        return quality_score is None or self._finite_float(quality_score)

    def _pit_timestamp_pair_ready(
        self,
        *,
        observed_value: object,
        retrieved_value: object,
        as_of: datetime,
    ) -> bool:
        observed_at = self._optional_aware_datetime(observed_value)
        retrieved_at = self._optional_aware_datetime(retrieved_value)
        return (
            observed_at is not None
            and retrieved_at is not None
            and observed_at <= retrieved_at
            and retrieved_at <= as_of
        )

    def _identity_consistent(self, *instrument_ids: int | None) -> bool:
        if any(value is None for value in instrument_ids):
            return False
        resolved = {int(value) for value in instrument_ids if value is not None}
        return len(resolved) == 1

    def _finite_float(self, value: object) -> bool:
        if isinstance(value, bool):
            return False
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return isfinite(numeric_value)

    def _float_at_least(self, value: object, threshold: float) -> bool:
        if not self._finite_float(value):
            return False
        return float(value) >= threshold

    def _positive_float(self, value: object) -> bool:
        if not self._finite_float(value):
            return False
        return float(value) > 0

    def _non_negative_float(self, value: object) -> bool:
        if not self._finite_float(value):
            return False
        return float(value) >= 0

    def _float_between(self, value: object, minimum: float, maximum: float) -> bool:
        if not self._finite_float(value):
            return False
        numeric_value = float(value)
        return minimum <= numeric_value <= maximum

    def _optional_int(self, value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    def _optional_aware_datetime(self, value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    def _parse_aware_datetime(self, value: object) -> datetime:
        parsed = self._optional_aware_datetime(value)
        if parsed is None:
            raise RuntimeError("El diagnóstico incluye un asOf inválido o sin zona horaria.")
        return parsed

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
