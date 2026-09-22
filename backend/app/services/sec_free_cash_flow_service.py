from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.sec_fundamental_evidence_resolver import SecFundamentalEvidenceResolver


class _FundamentalResolver(Protocol):
    def resolve(self, *, cik: str, canonical_concept: str, as_of: datetime) -> dict[str, object]: ...


@dataclass(frozen=True)
class SecFreeCashFlowDiagnostic:
    status: str
    cik: str
    as_of: str
    free_cash_flow: float | None
    unit: str | None
    period_start: str | None
    period_end: str | None
    operating_cash_flow: dict[str, Any] | None
    capital_expenditure: dict[str, Any] | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cik": self.cik,
            "asOf": self.as_of,
            "freeCashFlow": self.free_cash_flow,
            "unit": self.unit,
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "operatingCashFlow": self.operating_cash_flow,
            "capitalExpenditure": self.capital_expenditure,
            "productionEligible": self.production_eligible,
            "policy": {
                "formula": "annual_operating_cash_flow_minus_annual_capital_expenditure",
                "period": "same_period_required",
                "unit": "same_unit_required",
                "temporal": "both_sec_facts_must_be_known_by_same_as_of",
                "missingEvidence": "reported_missing_never_imputed",
                "authority": "diagnostic_only_not_recommendation_or_trading_authority",
            },
            "reason": self.reason,
        }


class SecFreeCashFlowService:
    """Compose annual SEC cash-flow evidence without mixing periods or vintages."""

    def __init__(self, resolver: _FundamentalResolver | None = None) -> None:
        self._resolver = resolver or SecFundamentalEvidenceResolver()

    def evaluate(self, *, cik: str, as_of: datetime) -> SecFreeCashFlowDiagnostic:
        cutoff = self._aware_utc(as_of)
        ocf = self._resolver.resolve(cik=cik, canonical_concept="operating_cash_flow_annual", as_of=cutoff)
        capex = self._resolver.resolve(cik=cik, canonical_concept="capital_expenditure_annual", as_of=cutoff)
        normalized_cik = str(ocf.get("cik") or capex.get("cik") or cik)
        common = dict(cik=normalized_cik, as_of=cutoff.isoformat(), production_eligible=False)
        if ocf.get("status") != "resolved" or capex.get("status") != "resolved":
            return SecFreeCashFlowDiagnostic(status="evidence_missing", free_cash_flow=None, unit=None, period_start=None, period_end=None, operating_cash_flow=self._fact(ocf), capital_expenditure=self._fact(capex), reason="FCF anual requiere OCF y CAPEX SEC point-in-time; ATHENA no imputa el componente ausente.", **common)
        ocf_fact, capex_fact = self._fact(ocf), self._fact(capex)
        if ocf_fact is None or capex_fact is None:
            raise RuntimeError("El resolver SEC marcó evidencia resuelta sin selectedFact.")
        if ocf_fact.get("periodStart") != capex_fact.get("periodStart") or ocf_fact.get("periodEnd") != capex_fact.get("periodEnd"):
            return SecFreeCashFlowDiagnostic(status="period_mismatch", free_cash_flow=None, unit=None, period_start=None, period_end=None, operating_cash_flow=ocf_fact, capital_expenditure=capex_fact, reason="OCF y CAPEX pertenecen a periodos económicos distintos; no se calcula FCF.", **common)
        ocf_unit, capex_unit = str(ocf_fact.get("unit") or ""), str(capex_fact.get("unit") or "")
        if not ocf_unit or ocf_unit != capex_unit:
            return SecFreeCashFlowDiagnostic(status="unit_mismatch", free_cash_flow=None, unit=None, period_start=None, period_end=None, operating_cash_flow=ocf_fact, capital_expenditure=capex_fact, reason="OCF y CAPEX no comparten unidad monetaria; no se calcula FCF.", **common)
        ocf_value, capex_value = self._number(ocf_fact.get("value")), self._number(capex_fact.get("value"))
        return SecFreeCashFlowDiagnostic(status="diagnostic_ready", free_cash_flow=ocf_value - capex_value, unit=ocf_unit, period_start=str(ocf_fact.get("periodStart")), period_end=str(ocf_fact.get("periodEnd")), operating_cash_flow=ocf_fact, capital_expenditure=capex_fact, reason="FCF anual derivado de OCF menos CAPEX SEC comparables y conocidos en el mismo corte PIT.", **common)

    @staticmethod
    def _fact(payload: dict[str, object]) -> dict[str, Any] | None:
        fact = payload.get("selectedFact")
        return dict(fact) if isinstance(fact, dict) else None

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool):
            raise RuntimeError("Fact SEC numérico inválido.")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Fact SEC numérico inválido.") from exc

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
