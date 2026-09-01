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
    assert "10-K" in (datum.provenance.version or "")
    assert "0000320193-25-000079" in (datum.provenance.version or "")


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
