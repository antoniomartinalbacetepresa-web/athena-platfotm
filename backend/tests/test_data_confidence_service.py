from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.services.data_confidence_service import DataConfidenceService


def _datum(source: str, value: float, quality: float) -> NormalizedDatum:
    return NormalizedDatum(
        metric="ebitda",
        value=value,
        data_kind="fact",
        provenance=DataProvenance(
            source_id=source,
            retrieved_at="2026-09-01T00:00:00+00:00",
        ),
        quality_score=quality,
    )


def test_confidence_is_high_when_good_sources_agree() -> None:
    result = DataConfidenceService().assess(
        [
            _datum("sec_edgar_xbrl", 100.0, 99.0),
            _datum("stock_analysis", 101.0, 80.0),
            _datum("tikr", 99.5, 80.0),
        ]
    )

    assert result.confidence_score > 85
    assert result.has_discrepancy is False
    assert result.observations_used == 3


def test_confidence_flags_material_source_disagreement() -> None:
    result = DataConfidenceService().assess(
        [
            _datum("sec_edgar_xbrl", 100.0, 99.0),
            _datum("secondary_source", 125.0, 70.0),
        ],
        discrepancy_threshold_pct=5.0,
    )

    assert result.has_discrepancy is True
    assert result.agreement_score < 100
    assert result.confidence_score < 90


def test_confidence_rejects_mixed_metrics() -> None:
    first = _datum("one", 100.0, 90.0)
    second = NormalizedDatum(
        metric="revenue",
        value=100.0,
        data_kind="fact",
        provenance=DataProvenance(
            source_id="two",
            retrieved_at="2026-09-01T00:00:00+00:00",
        ),
        quality_score=90.0,
    )

    try:
        DataConfidenceService().assess([first, second])
    except ValueError as exc:
        assert "same metric" in str(exc)
    else:
        raise AssertionError("Expected mixed metrics to be rejected.")
