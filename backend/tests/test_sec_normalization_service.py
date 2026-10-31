from app.services.point_in_time_data_service import PointInTimeDataService
from app.services.sec_normalization_service import SecNormalizationService


def test_normalize_company_fact_preserves_point_in_time_provenance() -> None:
    service = SecNormalizationService()

    datum = service.normalize_company_fact(
        cik="320193",
        taxonomy="us-gaap",
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        unit="USD",
        observation={
            "val": 1000,
            "end": "2025-09-27",
            "filed": "2025-10-31",
            "form": "10-K",
            "accn": "0000320193-25-000079",
            "frame": "CY2025",
        },
    )

    assert datum.metric == (
        "fundamental.us-gaap."
        "revenuefromcontractwithcustomerexcludingassessedtax"
    )
    assert datum.value == 1000
    assert datum.data_kind == "fact"
    assert datum.entity_id == "sec-cik:0000320193"
    assert datum.unit == "USD"
    assert datum.quality_score == 100.0
    assert datum.provenance.source_id == "sec_edgar_xbrl"
    assert datum.provenance.effective_at == "2025-09-27"
    assert datum.provenance.published_at == "2025-10-31"
    assert datum.provenance.available_at == "2025-11-01T00:00:00+00:00"
    assert "10-K" in (datum.provenance.version or "")
    assert "0000320193-25-000079" in (datum.provenance.version or "")


def test_sec_date_only_filing_is_not_available_during_filing_day() -> None:
    normalization = SecNormalizationService()
    point_in_time = PointInTimeDataService()

    datum = normalization.normalize_company_fact(
        cik="320193",
        taxonomy="us-gaap",
        concept="NetIncomeLoss",
        unit="USD",
        observation={
            "val": 12,
            "end": "2025-09-27",
            "filed": "2025-10-31",
        },
    )

    before = point_in_time.evaluate(
        datum.provenance,
        as_of="2025-10-31T23:59:59+00:00",
    )
    after = point_in_time.evaluate(
        datum.provenance,
        as_of="2025-11-01T00:00:00+00:00",
    )

    assert before.available is False
    assert before.reason == "available_after_as_of"
    assert after.available is True
    assert after.reason == "available_at_or_before_as_of"


def test_sec_missing_or_invalid_filed_date_remains_unavailable() -> None:
    service = SecNormalizationService()
    point_in_time = PointInTimeDataService()

    for filed in (None, "not-a-date"):
        datum = service.normalize_company_fact(
            cik="320193",
            taxonomy="us-gaap",
            concept="Assets",
            unit="USD",
            observation={
                "val": 100,
                "end": "2025-09-27",
                "filed": filed,
            },
        )

        assessment = point_in_time.evaluate(
            datum.provenance,
            as_of="2026-01-01T00:00:00+00:00",
        )

        assert datum.provenance.available_at is None
        assert assessment.available is False
        assert assessment.reason == "explicit_availability_timestamp_required"


def test_normalize_concept_units_keeps_multiple_historical_observations() -> None:
    service = SecNormalizationService()

    data = service.normalize_concept_units(
        cik="320193",
        taxonomy="us-gaap",
        concept="NetIncomeLoss",
        units={
            "USD": [
                {"val": 10, "end": "2024-09-28", "filed": "2024-11-01"},
                {"val": 12, "end": "2025-09-27", "filed": "2025-10-31"},
            ]
        },
    )

    assert [datum.value for datum in data] == [10, 12]
    assert [datum.provenance.effective_at for datum in data] == [
        "2024-09-28",
        "2025-09-27",
    ]
    assert [datum.provenance.available_at for datum in data] == [
        "2024-11-02T00:00:00+00:00",
        "2025-11-01T00:00:00+00:00",
    ]
