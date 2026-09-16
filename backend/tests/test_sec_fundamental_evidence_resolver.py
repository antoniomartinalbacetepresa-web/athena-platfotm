from datetime import datetime, timezone

import pytest

from app.services.sec_fundamental_evidence_resolver import SecFundamentalEvidenceResolver


UTC = timezone.utc
AS_OF = datetime(2026, 3, 1, 12, tzinfo=UTC)


class FakeRepository:
    def __init__(self, artifacts):
        self.artifacts = list(artifacts)
        self.calls = []

    def get_known_at_or_before(self, *, cik, as_of, concept=None):
        self.calls.append((cik, as_of, concept))
        return [{"artifact": artifact} for artifact in self.artifacts]


def fact(
    *,
    key: str,
    concept: str,
    value: float,
    period_end: str,
    period_start: str | None,
    available_at: str,
    form: str = "10-K",
    accession: str = "0000000000-26-000001",
    taxonomy: str = "us-gaap",
    unit: str = "USD",
):
    return {
        "factKey": key * 64,
        "cik": "0000123456",
        "taxonomy": taxonomy,
        "concept": concept,
        "unit": unit,
        "value": value,
        "periodStart": period_start,
        "periodEnd": period_end,
        "fiscalYear": 2025,
        "fiscalPeriod": "FY" if form.startswith("10-K") else "Q1",
        "form": form,
        "accessionNumber": accession,
        "filedAt": available_at.split("T")[0] + "T00:00:00+00:00",
        "availableAt": available_at,
        "provenance": {
            "source": "sec_edgar",
            "sourceRef": f"sec:0000123456:{accession}:{concept}",
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
    }


def test_resolver_selects_latest_economic_period_and_latest_known_revision() -> None:
    repository = FakeRepository(
        [
            fact(
                key="a",
                concept="Assets",
                value=100.0,
                period_start=None,
                period_end="2024-12-31",
                available_at="2025-02-01T12:00:00+00:00",
            ),
            fact(
                key="b",
                concept="Assets",
                value=120.0,
                period_start=None,
                period_end="2025-12-31",
                available_at="2026-02-01T12:00:00+00:00",
            ),
            fact(
                key="c",
                concept="Assets",
                value=121.0,
                period_start=None,
                period_end="2025-12-31",
                available_at="2026-02-15T12:00:00+00:00",
                form="10-K/A",
                accession="0000000000-26-000002",
            ),
        ]
    )
    result = SecFundamentalEvidenceResolver(repository).resolve(
        cik="123456",
        canonical_concept="assets",
        as_of=AS_OF,
    )

    assert result["status"] == "resolved"
    assert result["selectedFact"]["factKey"] == "c" * 64
    assert result["selectedFact"]["value"] == 121.0
    assert result["selectedFact"]["periodEnd"] == "2025-12-31"
    assert result["policy"]["revisionHandling"] == "latest_known_vintage_within_selected_period"
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert len(result["evidenceKey"]) == 64


def test_resolver_uses_explicit_concept_priority_for_same_period() -> None:
    repository = FakeRepository(
        [
            fact(
                key="d",
                concept="Revenues",
                value=99.0,
                period_start="2025-01-01",
                period_end="2025-12-31",
                available_at="2026-02-01T12:00:00+00:00",
            ),
            fact(
                key="e",
                concept="RevenueFromContractWithCustomerExcludingAssessedTax",
                value=100.0,
                period_start="2025-01-01",
                period_end="2025-12-31",
                available_at="2026-01-31T12:00:00+00:00",
            ),
        ]
    )
    result = SecFundamentalEvidenceResolver(repository).resolve(
        cik="123456",
        canonical_concept="revenue_annual",
        as_of=AS_OF,
    )

    assert result["selectedFact"]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert result["selectedFact"]["value"] == 100.0


def test_resolver_does_not_mix_ytd_with_quarter_duration() -> None:
    repository = FakeRepository(
        [
            fact(
                key="f",
                concept="NetIncomeLoss",
                value=30.0,
                period_start="2025-01-01",
                period_end="2025-09-30",
                available_at="2025-11-01T12:00:00+00:00",
                form="10-Q",
            ),
            fact(
                key="1",
                concept="NetIncomeLoss",
                value=12.0,
                period_start="2025-07-01",
                period_end="2025-09-30",
                available_at="2025-11-01T12:00:00+00:00",
                form="10-Q",
                accession="0000000000-25-000010",
            ),
        ]
    )
    result = SecFundamentalEvidenceResolver(repository).resolve(
        cik="123456",
        canonical_concept="net_income_quarter",
        as_of=AS_OF,
    )

    assert result["selectedFact"]["value"] == 12.0
    assert result["selectedFact"]["periodStart"] == "2025-07-01"


def test_resolver_reports_missing_instead_of_imputing_or_cross_taxonomy_mapping() -> None:
    repository = FakeRepository(
        [
            fact(
                key="2",
                concept="Assets",
                value=100.0,
                period_start=None,
                period_end="2025-12-31",
                available_at="2026-02-01T12:00:00+00:00",
                taxonomy="ifrs-full",
            )
        ]
    )
    result = SecFundamentalEvidenceResolver(repository).resolve(
        cik="123456",
        canonical_concept="assets",
        as_of=AS_OF,
    )

    assert result["status"] == "missing"
    assert result["selectedFact"] is None
    assert result["evidenceKey"] is None
    assert result["policy"]["taxonomy"] == "us-gaap_only_fail_closed"
    assert result["policy"]["missingEvidence"] == "reported_missing_never_imputed"


def test_resolver_rejects_future_repository_leak_and_nonfinite_value() -> None:
    future = fact(
        key="3",
        concept="Assets",
        value=100.0,
        period_start=None,
        period_end="2025-12-31",
        available_at="2026-03-02T12:00:00+00:00",
    )
    with pytest.raises(ValueError, match="futura"):
        SecFundamentalEvidenceResolver(FakeRepository([future])).resolve(
            cik="123456",
            canonical_concept="assets",
            as_of=AS_OF,
        )

    bad = fact(
        key="4",
        concept="Assets",
        value=float("nan"),
        period_start=None,
        period_end="2025-12-31",
        available_at="2026-02-01T12:00:00+00:00",
    )
    with pytest.raises(ValueError, match="finito"):
        SecFundamentalEvidenceResolver(FakeRepository([bad])).resolve(
            cik="123456",
            canonical_concept="assets",
            as_of=AS_OF,
        )


def test_resolver_rejects_naive_as_of_and_unknown_concept() -> None:
    resolver = SecFundamentalEvidenceResolver(FakeRepository([]))
    with pytest.raises(ValueError, match="zona horaria"):
        resolver.resolve(
            cik="123456",
            canonical_concept="assets",
            as_of=datetime(2026, 3, 1, 12),
        )
    with pytest.raises(ValueError, match="no soportado"):
        resolver.resolve(
            cik="123456",
            canonical_concept="free_cash_flow_magic",
            as_of=AS_OF,
        )
