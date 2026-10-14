from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from typing import Any, Mapping


@dataclass(frozen=True)
class FundamentalPitFact:
    fact_key: str
    cik: str
    taxonomy: str
    concept: str
    unit: str
    value: float
    period_start: date | None
    period_end: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str
    accession_number: str
    filed_at: datetime
    available_at: datetime
    source: str
    source_ref: str

    def to_api_dict(self) -> dict[str, object]:
        return {
            "factKey": self.fact_key,
            "cik": self.cik,
            "taxonomy": self.taxonomy,
            "concept": self.concept,
            "unit": self.unit,
            "value": self.value,
            "periodStart": self.period_start.isoformat() if self.period_start else None,
            "periodEnd": self.period_end.isoformat(),
            "fiscalYear": self.fiscal_year,
            "fiscalPeriod": self.fiscal_period,
            "form": self.form,
            "accessionNumber": self.accession_number,
            "filedAt": self.filed_at.isoformat(),
            "availableAt": self.available_at.isoformat(),
            "provenance": {"source": self.source, "sourceRef": self.source_ref},
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "temporal": "period_end_lte_filed_at_lte_available_at",
                "lookahead": "forbidden",
                "availabilityEvidence": "explicit_sec_acceptance_datetime_required",
                "revisionHandling": "accession_bound_vintages_preserved",
                "identity": "deterministic_sha256_fact_key",
                "source": "sec_edgar_companyfacts_plus_submissions",
            },
        }


class SecFundamentalPitService:
    """Normalize SEC CompanyFacts into accession-bound point-in-time evidence."""

    _ALLOWED_FORMS = {
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "20-F",
        "20-F/A",
        "40-F",
        "40-F/A",
    }

    def normalize(
        self,
        *,
        cik: str,
        company_facts: Mapping[str, Any],
        submissions: Mapping[str, Any],
        as_of: datetime,
    ) -> tuple[FundamentalPitFact, ...]:
        as_of_utc = self._aware_utc(as_of, "as_of")
        normalized_cik = self._cik(cik)
        payload_cik = self._cik(company_facts.get("cik", normalized_cik))
        if payload_cik != normalized_cik:
            raise ValueError("CompanyFacts pertenece a otro CIK.")
        acceptance_by_accession = self._acceptance_index(submissions)
        facts_root = company_facts.get("facts")
        if not isinstance(facts_root, Mapping):
            raise ValueError("CompanyFacts carece de facts válidos.")

        output: dict[str, FundamentalPitFact] = {}
        for taxonomy_raw, concepts_raw in facts_root.items():
            taxonomy = self._text(taxonomy_raw, "taxonomy")
            if not isinstance(concepts_raw, Mapping):
                continue
            for concept_raw, concept_payload in concepts_raw.items():
                concept = self._text(concept_raw, "concept")
                if not isinstance(concept_payload, Mapping):
                    continue
                units = concept_payload.get("units")
                if not isinstance(units, Mapping):
                    continue
                for unit_raw, observations in units.items():
                    unit = self._text(unit_raw, "unit")
                    if not isinstance(observations, list):
                        continue
                    for raw in observations:
                        if not isinstance(raw, Mapping):
                            continue
                        fact = self._normalize_observation(
                            cik=normalized_cik,
                            taxonomy=taxonomy,
                            concept=concept,
                            unit=unit,
                            raw=raw,
                            acceptance_by_accession=acceptance_by_accession,
                            as_of=as_of_utc,
                        )
                        if fact is None:
                            continue
                        existing = output.get(fact.fact_key)
                        if existing is not None and existing != fact:
                            raise ValueError(
                                "SEC produjo dos facts distintos con la misma identidad canónica."
                            )
                        output[fact.fact_key] = fact
        return tuple(
            sorted(
                output.values(),
                key=lambda item: (
                    item.available_at,
                    item.taxonomy,
                    item.concept,
                    item.unit,
                    item.fact_key,
                ),
            )
        )

    def _normalize_observation(
        self,
        *,
        cik: str,
        taxonomy: str,
        concept: str,
        unit: str,
        raw: Mapping[str, Any],
        acceptance_by_accession: Mapping[str, datetime],
        as_of: datetime,
    ) -> FundamentalPitFact | None:
        form = str(raw.get("form") or "").strip().upper()
        if form not in self._ALLOWED_FORMS:
            return None
        accession = self._text(raw.get("accn"), "accn")
        available_at = acceptance_by_accession.get(accession)
        if available_at is None:
            return None
        filed_date = self._date(raw.get("filed"), "filed")
        period_end = self._date(raw.get("end"), "end")
        period_start = self._optional_date(raw.get("start"), "start")
        if period_start is not None and period_start > period_end:
            raise ValueError("Un fact SEC tiene start posterior a end.")
        filed_at = datetime.combine(filed_date, time.min, tzinfo=timezone.utc)
        if period_end > filed_date:
            raise ValueError("Un fact SEC termina después de su filing date.")
        if filed_at > available_at:
            raise ValueError("acceptanceDateTime no puede preceder filingDate.")
        if available_at > as_of:
            return None
        value = self._finite(raw.get("val"), "val")
        fiscal_year = raw.get("fy")
        if fiscal_year is not None:
            if isinstance(fiscal_year, bool):
                raise ValueError("fy inválido.")
            try:
                fiscal_year = int(fiscal_year)
            except (TypeError, ValueError) as exc:
                raise ValueError("fy inválido.") from exc
        fiscal_period = str(raw.get("fp") or "").strip().upper() or None
        source_ref = (
            f"sec:{cik}:{accession}:{taxonomy}:{concept}:{unit}:"
            f"{period_start}:{period_end}"
        )
        identity = {
            "cik": cik,
            "taxonomy": taxonomy,
            "concept": concept,
            "unit": unit,
            "value": format(value, ".17g"),
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat(),
            "fiscalYear": fiscal_year,
            "fiscalPeriod": fiscal_period,
            "form": form,
            "accessionNumber": accession,
            "filedAt": filed_at.isoformat(),
            "availableAt": available_at.isoformat(),
            "source": "sec_edgar",
            "sourceRef": source_ref,
        }
        key = hashlib.sha256(
            json.dumps(
                identity,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return FundamentalPitFact(
            fact_key=key,
            cik=cik,
            taxonomy=taxonomy,
            concept=concept,
            unit=unit,
            value=value,
            period_start=period_start,
            period_end=period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            form=form,
            accession_number=accession,
            filed_at=filed_at,
            available_at=available_at,
            source="sec_edgar",
            source_ref=source_ref,
        )

    def _acceptance_index(self, submissions: Mapping[str, Any]) -> dict[str, datetime]:
        filings = submissions.get("filings")
        if not isinstance(filings, Mapping):
            return {}
        recent = filings.get("recent")
        if not isinstance(recent, Mapping):
            return {}
        accessions = recent.get("accessionNumber")
        acceptances = recent.get("acceptanceDateTime")
        if not isinstance(accessions, list) or not isinstance(acceptances, list):
            return {}
        result: dict[str, datetime] = {}
        for index, accession_raw in enumerate(accessions):
            if index >= len(acceptances):
                break
            accession = str(accession_raw or "").strip()
            acceptance_raw = acceptances[index]
            if not accession or not acceptance_raw:
                continue
            result[accession] = self._parse_datetime(
                acceptance_raw,
                "acceptanceDateTime",
            )
        return result

    @staticmethod
    def _cik(raw: object) -> str:
        digits = "".join(char for char in str(raw or "") if char.isdigit())
        if not digits or len(digits) > 10:
            raise ValueError("CIK inválido.")
        return digits.zfill(10)

    @staticmethod
    def _text(raw: object, field: str) -> str:
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"{field} es obligatorio.")
        return value

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
    def _date(raw: object, field: str) -> date:
        try:
            return date.fromisoformat(str(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser fecha ISO válida.") from exc

    @classmethod
    def _optional_date(cls, raw: object, field: str) -> date | None:
        if raw in (None, ""):
            return None
        return cls._date(raw, field)

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        text = str(raw or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field} debe ser timestamp ISO válido.") from exc
        return cls._aware_utc(value, field)
