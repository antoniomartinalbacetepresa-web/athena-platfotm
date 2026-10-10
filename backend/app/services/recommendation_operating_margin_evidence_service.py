from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping

from app.services.sec_fundamental_evidence_resolver import SecFundamentalEvidenceResolver
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolver


class RecommendationOperatingMarginEvidenceService:
    """Build issuer-bound annual PIT operating-margin evidence.

    Revenue and operating income must resolve from the exact same SEC filing and
    accounting period. The raw ratio is descriptive evidence, never a quality
    score, recommendation, or sizing input by itself.
    """

    def __init__(
        self,
        *,
        cik_resolver: SecInstrumentCikResolver | None = None,
        fundamental_resolver: SecFundamentalEvidenceResolver | None = None,
    ) -> None:
        self._cik_resolver = cik_resolver or SecInstrumentCikResolver()
        self._fundamental_resolver = fundamental_resolver or SecFundamentalEvidenceResolver()

    def evaluate(self, *, instrument_id: int, as_of: datetime) -> dict[str, object]:
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        cutoff = self._aware_utc(as_of, "as_of")
        identity = self._cik_resolver.resolve(instrument_id=instrument_id)
        identity_payload = identity.to_api_dict()
        revenue = self._fundamental_resolver.resolve(
            cik=identity.cik,
            canonical_concept="revenue_annual",
            as_of=cutoff,
        )
        operating_income = self._fundamental_resolver.resolve(
            cik=identity.cik,
            canonical_concept="operating_income_annual",
            as_of=cutoff,
        )
        if revenue.get("status") != "resolved":
            return self._missing(
                instrument_id=instrument_id,
                as_of=cutoff,
                identity=identity_payload,
                reason="revenue_annual_missing",
                revenue_evidence=revenue,
                operating_income_evidence=operating_income,
            )
        if operating_income.get("status") != "resolved":
            return self._missing(
                instrument_id=instrument_id,
                as_of=cutoff,
                identity=identity_payload,
                reason="operating_income_annual_missing",
                revenue_evidence=revenue,
                operating_income_evidence=operating_income,
            )

        revenue_fact = self._selected(revenue, "revenue")
        income_fact = self._selected(operating_income, "operating_income")
        comparable_fields = ("periodStart", "periodEnd", "accessionNumber")
        if any(revenue_fact.get(field) != income_fact.get(field) for field in comparable_fields):
            return self._missing(
                instrument_id=instrument_id,
                as_of=cutoff,
                identity=identity_payload,
                reason="annual_facts_not_same_period_and_accession",
                revenue_evidence=revenue,
                operating_income_evidence=operating_income,
            )

        revenue_value = self._finite(revenue_fact.get("value"), "revenue.value")
        operating_income_value = self._finite(
            income_fact.get("value"), "operating_income.value"
        )
        if revenue_value <= 0.0:
            return self._missing(
                instrument_id=instrument_id,
                as_of=cutoff,
                identity=identity_payload,
                reason="revenue_annual_non_positive",
                revenue_evidence=revenue,
                operating_income_evidence=operating_income,
            )
        margin = self._finite(operating_income_value / revenue_value, "operatingMargin")

        identity_key = str(identity_payload.get("identityKey") or "")
        revenue_key = str(revenue.get("evidenceKey") or "")
        income_key = str(operating_income.get("evidenceKey") or "")
        if not all(self._sha256(key) for key in (identity_key, revenue_key, income_key)):
            raise ValueError("Operating margin perdió hashes upstream válidos.")
        available_at = max(
            self._parse_datetime(revenue_fact.get("availableAt"), "revenue.availableAt"),
            self._parse_datetime(income_fact.get("availableAt"), "operatingIncome.availableAt"),
        )
        if available_at > cutoff:
            raise ValueError("Operating margin violó PIT/no-lookahead.")
        canonical = {
            "instrumentId": instrument_id,
            "asOf": cutoff.isoformat(),
            "availableAt": available_at.isoformat(),
            "identityKey": identity_key,
            "cik": str(identity.cik),
            "revenueEvidenceKey": revenue_key,
            "operatingIncomeEvidenceKey": income_key,
            "periodStart": revenue_fact.get("periodStart"),
            "periodEnd": revenue_fact.get("periodEnd"),
            "accessionNumber": revenue_fact.get("accessionNumber"),
            "revenueUsd": format(revenue_value, ".17g"),
            "operatingIncomeUsd": format(operating_income_value, ".17g"),
            "operatingMargin": format(margin, ".17g"),
        }
        evidence_key = self._hash(canonical)
        artifact: dict[str, object] = {
            "module": "operating_margin_pit_evidence",
            "status": "resolved",
            "evidenceKey": evidence_key,
            "instrumentId": instrument_id,
            "asOf": cutoff.isoformat(),
            "availableAt": available_at.isoformat(),
            "cik": str(identity.cik),
            "periodStart": revenue_fact.get("periodStart"),
            "periodEnd": revenue_fact.get("periodEnd"),
            "accessionNumber": revenue_fact.get("accessionNumber"),
            "revenueUsd": revenue_value,
            "operatingIncomeUsd": operating_income_value,
            "operatingMargin": margin,
            "identityEvidence": identity_payload,
            "revenueEvidence": revenue,
            "operatingIncomeEvidence": operating_income,
            "factorReady": False,
            "factorExposure": None,
            "policy": self._policy(),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }
        return self.validate_artifact(artifact)

    def validate_artifact(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        data = dict(artifact)
        if data.get("module") != "operating_margin_pit_evidence" or data.get("status") != "resolved":
            raise ValueError("Operating margin artifact resuelto inválido.")
        if data.get("advisoryStatus") != "no_advice":
            raise ValueError("Operating margin violó no_advice.")
        if data.get("productionEligible") is not False or data.get("isWeightingReady") is not False:
            raise ValueError("Operating margin intentó habilitar producción/weighting.")
        if data.get("factorReady") is not False or data.get("factorExposure") is not None:
            raise ValueError("Operating margin bruto no puede presentarse como factor.")
        instrument_id = data.get("instrumentId")
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("Operating margin perdió instrumentId.")
        cutoff = self._parse_datetime(data.get("asOf"), "asOf")
        available = self._parse_datetime(data.get("availableAt"), "availableAt")
        if available > cutoff:
            raise ValueError("Operating margin viola PIT/no-lookahead.")
        revenue_value = self._finite(data.get("revenueUsd"), "revenueUsd")
        income_value = self._finite(data.get("operatingIncomeUsd"), "operatingIncomeUsd")
        margin = self._finite(data.get("operatingMargin"), "operatingMargin")
        if revenue_value <= 0.0:
            raise ValueError("Operating margin exige revenue positivo.")
        if not math.isclose(margin, income_value / revenue_value, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("operatingMargin no reconcilia con income/revenue.")
        identity = data.get("identityEvidence")
        revenue = data.get("revenueEvidence")
        income = data.get("operatingIncomeEvidence")
        if not all(isinstance(item, Mapping) for item in (identity, revenue, income)):
            raise ValueError("Operating margin perdió evidencia/provenance.")
        assert isinstance(identity, Mapping) and isinstance(revenue, Mapping) and isinstance(income, Mapping)
        if identity.get("instrumentId") != instrument_id or str(identity.get("cik")) != str(data.get("cik")):
            raise ValueError("Operating margin perdió binding de identidad.")
        revenue_fact = self._selected(revenue, "revenue")
        income_fact = self._selected(income, "operating_income")
        for field in ("periodStart", "periodEnd", "accessionNumber"):
            if revenue_fact.get(field) != income_fact.get(field) or revenue_fact.get(field) != data.get(field):
                raise ValueError("Operating margin mezcló periodos/accessions incompatibles.")
        if self._finite(revenue_fact.get("value"), "revenue.value") != revenue_value:
            raise ValueError("Operating margin perdió binding con revenue.")
        if self._finite(income_fact.get("value"), "operating_income.value") != income_value:
            raise ValueError("Operating margin perdió binding con operating income.")
        identity_key = str(identity.get("identityKey") or "")
        revenue_key = str(revenue.get("evidenceKey") or "")
        income_key = str(income.get("evidenceKey") or "")
        if not all(self._sha256(key) for key in (identity_key, revenue_key, income_key)):
            raise ValueError("Operating margin perdió hashes upstream.")
        canonical = {
            "instrumentId": instrument_id,
            "asOf": cutoff.isoformat(),
            "availableAt": available.isoformat(),
            "identityKey": identity_key,
            "cik": str(data.get("cik")),
            "revenueEvidenceKey": revenue_key,
            "operatingIncomeEvidenceKey": income_key,
            "periodStart": data.get("periodStart"),
            "periodEnd": data.get("periodEnd"),
            "accessionNumber": data.get("accessionNumber"),
            "revenueUsd": format(revenue_value, ".17g"),
            "operatingIncomeUsd": format(income_value, ".17g"),
            "operatingMargin": format(margin, ".17g"),
        }
        if str(data.get("evidenceKey") or "") != self._hash(canonical):
            raise ValueError("Operating margin artifact fue manipulado.")
        policy = data.get("policy")
        if not isinstance(policy, Mapping) or policy.get("automaticTrading") is not False or policy.get("thresholds") != "not_calibrated":
            raise ValueError("Operating margin perdió límites de seguridad.")
        return data

    def _missing(
        self,
        *,
        instrument_id: int,
        as_of: datetime,
        identity: Mapping[str, Any],
        reason: str,
        revenue_evidence: Mapping[str, Any],
        operating_income_evidence: Mapping[str, Any],
    ) -> dict[str, object]:
        return {
            "module": "operating_margin_pit_evidence",
            "status": "missing",
            "evidenceKey": None,
            "instrumentId": instrument_id,
            "asOf": as_of.isoformat(),
            "availableAt": None,
            "missingReason": reason,
            "operatingMargin": None,
            "identityEvidence": dict(identity),
            "revenueEvidence": dict(revenue_evidence),
            "operatingIncomeEvidence": dict(operating_income_evidence),
            "factorReady": False,
            "factorExposure": None,
            "policy": self._policy(),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }

    @staticmethod
    def _policy() -> dict[str, object]:
        return {
            "metric": "annual_operating_income_usd_over_revenue_usd",
            "issuerBinding": "canonical_instrument_to_unique_sec_cik_required",
            "fundamentalSelection": "canonical_sec_pit_annual_resolver",
            "comparability": "same_period_start_end_and_accession_required",
            "qualityDefinition": "single_metric_operating_margin_not_composite_quality",
            "sectorNeutralization": "not_performed_or_claimed",
            "normalization": "not_yet_cross_sectionally_ranked",
            "factorReady": False,
            "thresholds": "not_calibrated",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
        }

    @staticmethod
    def _selected(evidence: Mapping[str, Any], label: str) -> Mapping[str, Any]:
        selected = evidence.get("selectedFact")
        if not isinstance(selected, Mapping):
            raise ValueError(f"{label} PIT resuelto carece de selectedFact.")
        return selected

    @staticmethod
    def _hash(payload: Mapping[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)

    @staticmethod
    def _finite(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{field} debe ser finito.")
        return value

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return cls._aware_utc(raw, field)
        text = str(raw or "").strip().replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._aware_utc(value, field)
