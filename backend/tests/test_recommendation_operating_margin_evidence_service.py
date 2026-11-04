from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_operating_margin_evidence_service import (
    RecommendationOperatingMarginEvidenceService,
)
from app.services.sec_instrument_cik_resolver import SecInstrumentCikResolution


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeCikResolver:
    def resolve(self, *, instrument_id: int) -> SecInstrumentCikResolution:
        return SecInstrumentCikResolution(
            instrument_id=instrument_id,
            issuer_id=100 + instrument_id,
            cik=str(instrument_id).zfill(10),
            issuer_name=f"Issuer {instrument_id}",
            link_confidence=1.0,
            external_id_confidence=1.0,
            evidence_source="test_identity",
            resolution_method="explicit_test",
            identity_key=(f"{instrument_id:x}"[-1] or "1") * 64,
        )


class FakeFundamentalResolver:
    def __init__(
        self,
        *,
        revenue: float = 100.0,
        income: float = 20.0,
        revenue_accession: str = "0001",
        income_accession: str = "0001",
        revenue_start: str = "2024-01-01",
        income_start: str = "2024-01-01",
        revenue_end: str = "2024-12-31",
        income_end: str = "2024-12-31",
        revenue_status: str = "resolved",
        income_status: str = "resolved",
    ) -> None:
        self.values = {
            "revenue_annual": (revenue, revenue_accession, revenue_start, revenue_end, revenue_status, "a" * 64),
            "operating_income_annual": (income, income_accession, income_start, income_end, income_status, "b" * 64),
        }

    def resolve(self, *, cik: str, canonical_concept: str, as_of: datetime) -> dict[str, object]:
        value, accession, start, end, status, key = self.values[canonical_concept]
        if status != "resolved":
            return {
                "module": "sec_fundamental_evidence_resolver",
                "status": "missing",
                "evidenceKey": None,
                "canonicalConcept": canonical_concept,
            }
        return {
            "module": "sec_fundamental_evidence_resolver",
            "status": "resolved",
            "evidenceKey": key,
            "cik": cik,
            "canonicalConcept": canonical_concept,
            "selectedFact": {
                "value": value,
                "periodStart": start,
                "periodEnd": end,
                "accessionNumber": accession,
                "availableAt": "2025-02-15T00:00:00+00:00",
            },
        }


def service(**kwargs: object) -> RecommendationOperatingMarginEvidenceService:
    return RecommendationOperatingMarginEvidenceService(
        cik_resolver=FakeCikResolver(),
        fundamental_resolver=FakeFundamentalResolver(**kwargs),
    )


def test_operating_margin_resolves_same_filing_and_preserves_safety() -> None:
    artifact = service().evaluate(instrument_id=1, as_of=AS_OF)
    assert artifact["status"] == "resolved"
    assert artifact["operatingMargin"] == pytest.approx(0.2)
    assert artifact["accessionNumber"] == "0001"
    assert artifact["factorReady"] is False
    assert artifact["factorExposure"] is None
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["policy"]["qualityDefinition"] == "single_metric_operating_margin_not_composite_quality"
    assert artifact["policy"]["sectorNeutralization"] == "not_performed_or_claimed"


def test_operating_margin_fails_closed_on_period_or_accession_mismatch() -> None:
    accession = service(income_accession="0002").evaluate(instrument_id=1, as_of=AS_OF)
    assert accession["status"] == "missing"
    assert accession["missingReason"] == "annual_facts_not_same_period_and_accession"
    assert accession["operatingMargin"] is None

    period = service(income_start="2024-01-02").evaluate(instrument_id=1, as_of=AS_OF)
    assert period["status"] == "missing"
    assert period["missingReason"] == "annual_facts_not_same_period_and_accession"


def test_operating_margin_missing_or_nonpositive_revenue_is_never_scored() -> None:
    missing = service(revenue_status="missing").evaluate(instrument_id=1, as_of=AS_OF)
    assert missing["status"] == "missing"
    assert missing["missingReason"] == "revenue_annual_missing"

    zero = service(revenue=0.0).evaluate(instrument_id=1, as_of=AS_OF)
    assert zero["status"] == "missing"
    assert zero["missingReason"] == "revenue_annual_non_positive"


def test_operating_margin_rejects_nonfinite_and_naive_time() -> None:
    with pytest.raises(ValueError, match="finito"):
        service(income=float("nan")).evaluate(instrument_id=1, as_of=AS_OF)
    with pytest.raises(ValueError, match="zona horaria"):
        service().evaluate(instrument_id=1, as_of=datetime(2026, 1, 1))


def test_operating_margin_hash_detects_tampering() -> None:
    svc = service()
    artifact = svc.evaluate(instrument_id=1, as_of=AS_OF)
    artifact["operatingMargin"] = 0.9
    with pytest.raises(ValueError, match="reconcilia|manipulado"):
        svc.validate_artifact(artifact)
