from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping

from app.repositories.sec_fundamental_pit_repository import SecFundamentalPitRepository


@dataclass(frozen=True)
class FundamentalConceptPolicy:
    canonical_name: str
    period_kind: str
    concepts: tuple[str, ...]
    allowed_forms: tuple[str, ...]
    unit: str = "USD"


class SecFundamentalEvidenceResolver:
    """Resolve comparable SEC XBRL evidence strictly from PIT persisted facts.

    The resolver does not calculate investment scores. It selects one canonical,
    auditable fact for a requested accounting meaning using an explicit concept
    priority, period policy and the latest vintage that was actually known at
    ``as_of``. Missing/ambiguous evidence stays missing or fails closed.
    """

    _POLICIES: dict[str, FundamentalConceptPolicy] = {
        "assets": FundamentalConceptPolicy(
            canonical_name="assets",
            period_kind="instant",
            concepts=("Assets",),
            allowed_forms=("10-K", "10-K/A", "10-Q", "10-Q/A"),
        ),
        "liabilities": FundamentalConceptPolicy(
            canonical_name="liabilities",
            period_kind="instant",
            concepts=("Liabilities",),
            allowed_forms=("10-K", "10-K/A", "10-Q", "10-Q/A"),
        ),
        "stockholders_equity": FundamentalConceptPolicy(
            canonical_name="stockholders_equity",
            period_kind="instant",
            concepts=(
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            allowed_forms=("10-K", "10-K/A", "10-Q", "10-Q/A"),
        ),
        "revenue_annual": FundamentalConceptPolicy(
            canonical_name="revenue_annual",
            period_kind="annual_duration",
            concepts=(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ),
            allowed_forms=("10-K", "10-K/A"),
        ),
        "net_income_annual": FundamentalConceptPolicy(
            canonical_name="net_income_annual",
            period_kind="annual_duration",
            concepts=("NetIncomeLoss",),
            allowed_forms=("10-K", "10-K/A"),
        ),
        "operating_income_annual": FundamentalConceptPolicy(
            canonical_name="operating_income_annual",
            period_kind="annual_duration",
            concepts=("OperatingIncomeLoss",),
            allowed_forms=("10-K", "10-K/A"),
        ),
        "operating_cash_flow_annual": FundamentalConceptPolicy(
            canonical_name="operating_cash_flow_annual",
            period_kind="annual_duration",
            concepts=("NetCashProvidedByUsedInOperatingActivities",),
            allowed_forms=("10-K", "10-K/A"),
        ),
        "revenue_quarter": FundamentalConceptPolicy(
            canonical_name="revenue_quarter",
            period_kind="quarter_duration",
            concepts=(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ),
            allowed_forms=("10-Q", "10-Q/A"),
        ),
        "net_income_quarter": FundamentalConceptPolicy(
            canonical_name="net_income_quarter",
            period_kind="quarter_duration",
            concepts=("NetIncomeLoss",),
            allowed_forms=("10-Q", "10-Q/A"),
        ),
    }

    def __init__(self, repository: SecFundamentalPitRepository | None = None) -> None:
        self._repository = repository or SecFundamentalPitRepository()

    @classmethod
    def supported_concepts(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._POLICIES))

    def resolve(
        self,
        *,
        cik: str,
        canonical_concept: str,
        as_of: datetime,
    ) -> dict[str, object]:
        as_of_utc = self._aware_utc(as_of, "as_of")
        policy = self._POLICIES.get(str(canonical_concept).strip())
        if policy is None:
            raise ValueError("Concepto fundamental canónico no soportado.")

        records = self._repository.get_known_at_or_before(cik=cik, as_of=as_of_utc)
        candidates: list[dict[str, Any]] = []
        priority = {concept: index for index, concept in enumerate(policy.concepts)}
        for record in records:
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise ValueError("Registro fundamental carece de artifact válido.")
            candidate = self._candidate(artifact=artifact, policy=policy, priority=priority, as_of=as_of_utc)
            if candidate is not None:
                candidates.append(candidate)

        if not candidates:
            return self._missing_payload(policy=policy, cik=cik, as_of=as_of_utc)

        # Prefer the latest economic period. Within that period use the explicit
        # concept priority, then the latest SEC vintage known at as_of.
        latest_period_end = max(item["periodEndDate"] for item in candidates)
        period_candidates = [item for item in candidates if item["periodEndDate"] == latest_period_end]
        best_priority = min(int(item["conceptPriority"]) for item in period_candidates)
        concept_candidates = [
            item for item in period_candidates if int(item["conceptPriority"]) == best_priority
        ]
        concept_candidates.sort(
            key=lambda item: (
                item["availableAtDateTime"],
                str(item["accessionNumber"]),
                str(item["factKey"]),
            )
        )
        chosen = concept_candidates[-1]

        identity = {
            "cik": chosen["cik"],
            "canonicalConcept": policy.canonical_name,
            "periodKind": policy.period_kind,
            "asOf": as_of_utc.isoformat(),
            "factKey": chosen["factKey"],
            "taxonomy": chosen["taxonomy"],
            "concept": chosen["concept"],
            "unit": chosen["unit"],
            "value": format(float(chosen["value"]), ".17g"),
            "periodStart": chosen["periodStart"],
            "periodEnd": chosen["periodEnd"],
            "accessionNumber": chosen["accessionNumber"],
            "availableAt": chosen["availableAt"],
        }
        evidence_key = hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "module": "sec_fundamental_evidence_resolver",
            "status": "resolved",
            "evidenceKey": evidence_key,
            "cik": chosen["cik"],
            "canonicalConcept": policy.canonical_name,
            "periodKind": policy.period_kind,
            "asOf": as_of_utc.isoformat(),
            "selectedFact": {
                "factKey": chosen["factKey"],
                "taxonomy": chosen["taxonomy"],
                "concept": chosen["concept"],
                "unit": chosen["unit"],
                "value": chosen["value"],
                "periodStart": chosen["periodStart"],
                "periodEnd": chosen["periodEnd"],
                "fiscalYear": chosen["fiscalYear"],
                "fiscalPeriod": chosen["fiscalPeriod"],
                "form": chosen["form"],
                "accessionNumber": chosen["accessionNumber"],
                "filedAt": chosen["filedAt"],
                "availableAt": chosen["availableAt"],
                "provenance": chosen["provenance"],
            },
            "policy": self._policy_payload(policy),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }

    def _candidate(
        self,
        *,
        artifact: dict[str, Any],
        policy: FundamentalConceptPolicy,
        priority: Mapping[str, int],
        as_of: datetime,
    ) -> dict[str, Any] | None:
        if artifact.get("taxonomy") != "us-gaap":
            return None
        concept = str(artifact.get("concept") or "")
        if concept not in priority:
            return None
        if str(artifact.get("unit") or "").upper() != policy.unit:
            return None
        form = str(artifact.get("form") or "").upper()
        if form not in policy.allowed_forms:
            return None
        available_at = self._parse_datetime(artifact.get("availableAt"), "availableAt")
        if available_at > as_of:
            raise ValueError("El repositorio devolvió evidencia fundamental futura.")
        period_end = self._parse_date(artifact.get("periodEnd"), "periodEnd")
        period_start_raw = artifact.get("periodStart")
        period_start = (
            self._parse_date(period_start_raw, "periodStart")
            if period_start_raw not in (None, "")
            else None
        )
        if not self._period_matches(policy.period_kind, period_start, period_end):
            return None
        value = self._finite(artifact.get("value"), "value")
        fact_key = str(artifact.get("factKey") or "")
        if len(fact_key) != 64 or any(ch not in "0123456789abcdef" for ch in fact_key):
            raise ValueError("factKey fundamental inválido.")
        provenance = artifact.get("provenance")
        if not isinstance(provenance, dict) or provenance.get("source") != "sec_edgar":
            raise ValueError("Evidencia fundamental carece de provenance SEC válida.")
        return {
            **artifact,
            "value": value,
            "conceptPriority": priority[concept],
            "periodEndDate": period_end,
            "availableAtDateTime": available_at,
        }

    @staticmethod
    def _period_matches(kind: str, start: date | None, end: date) -> bool:
        if kind == "instant":
            return start is None
        if start is None or start > end:
            return False
        days = (end - start).days
        if kind == "annual_duration":
            return 300 <= days <= 400
        if kind == "quarter_duration":
            return 70 <= days <= 110
        raise ValueError("period_kind fundamental no soportado.")

    @staticmethod
    def _policy_payload(policy: FundamentalConceptPolicy) -> dict[str, object]:
        return {
            "taxonomy": "us-gaap_only_fail_closed",
            "conceptPriority": list(policy.concepts),
            "periodKind": policy.period_kind,
            "unit": policy.unit,
            "latestEconomicPeriod": "required",
            "revisionHandling": "latest_known_vintage_within_selected_period",
            "crossPeriodMixing": "forbidden",
            "ytdQuarterMixing": "forbidden_by_duration_window",
            "missingEvidence": "reported_missing_never_imputed",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "factorScoring": "not_performed_here",
        }

    def _missing_payload(
        self,
        *,
        policy: FundamentalConceptPolicy,
        cik: str,
        as_of: datetime,
    ) -> dict[str, object]:
        return {
            "module": "sec_fundamental_evidence_resolver",
            "status": "missing",
            "evidenceKey": None,
            "cik": self._normalize_cik(cik),
            "canonicalConcept": policy.canonical_name,
            "periodKind": policy.period_kind,
            "asOf": as_of.isoformat(),
            "selectedFact": None,
            "policy": self._policy_payload(policy),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }

    @staticmethod
    def _normalize_cik(raw: object) -> str:
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if not digits or len(digits) > 10:
            raise ValueError("CIK inválido.")
        return digits.zfill(10)

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
    def _parse_date(raw: object, field: str) -> date:
        try:
            return date.fromisoformat(str(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser fecha ISO válida.") from exc

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        text = str(raw or "").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._aware_utc(value, field)
