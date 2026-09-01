from app.models.normalized_data import DataProvenance, NormalizedDatum


def test_normalized_datum_preserves_provenance_and_kind() -> None:
    provenance = DataProvenance(
        source_id="sec_edgar_xbrl",
        retrieved_at="2026-09-01T00:00:00+00:00",
        effective_at="2026-06-30",
        published_at="2026-08-01T12:00:00+00:00",
        raw_identifier="us-gaap:OperatingIncomeLoss",
        normalized_identifier="ebit",
    )

    datum = NormalizedDatum(
        metric="ebit",
        value=123.4,
        unit="USDm",
        data_kind="fact",
        provenance=provenance,
        quality_score=98,
    )

    payload = datum.to_dict()
    assert payload["metric"] == "ebit"
    assert payload["data_kind"] == "fact"
    assert payload["provenance"]["source_id"] == "sec_edgar_xbrl"
    assert payload["provenance"]["normalized_identifier"] == "ebit"


def test_normalized_datum_rejects_invalid_scores() -> None:
    provenance = DataProvenance(
        source_id="test",
        retrieved_at="2026-09-01T00:00:00+00:00",
    )

    try:
        NormalizedDatum(
            metric="revenue",
            value=1,
            data_kind="fact",
            provenance=provenance,
            quality_score=101,
        )
    except ValueError as exc:
        assert "quality_score" in str(exc)
    else:
        raise AssertionError("Expected invalid score to be rejected.")
