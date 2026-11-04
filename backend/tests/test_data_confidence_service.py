import pytest

from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.services.data_confidence_service import DataConfidenceService


def _datum(
    source: str,
    value: float,
    quality: float,
    *,
    entity_id: str | None = None,
    effective_at: str | None = None,
    unit: str | None = None,
    currency: str | None = None,
    data_kind: str = "fact",
) -> NormalizedDatum:
    return NormalizedDatum(
        metric="ebitda",
        value=value,
        data_kind=data_kind,  # type: ignore[arg-type]
        provenance=DataProvenance(
            source_id=source,
            retrieved_at="2026-09-01T00:00:00+00:00",
            effective_at=effective_at,
        ),
        entity_id=entity_id,
        unit=unit,
        currency=currency,
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

    with pytest.raises(ValueError, match="same metric"):
        DataConfidenceService().assess([first, second])


def test_confidence_rejects_incompatible_entity_or_period_context() -> None:
    first = _datum(
        "one",
        100.0,
        90.0,
        entity_id="issuer:1",
        effective_at="2026-06-30",
        unit="USDm",
        currency="USD",
    )
    other_entity = _datum(
        "two",
        100.0,
        90.0,
        entity_id="issuer:2",
        effective_at="2026-06-30",
        unit="USDm",
        currency="USD",
    )
    other_period = _datum(
        "two",
        100.0,
        90.0,
        entity_id="issuer:1",
        effective_at="2026-03-31",
        unit="USDm",
        currency="USD",
    )

    with pytest.raises(ValueError, match="share data_kind"):
        DataConfidenceService().assess([first, other_entity])

    with pytest.raises(ValueError, match="share data_kind"):
        DataConfidenceService().assess([first, other_period])


def test_confidence_rejects_duplicate_observations_from_same_source() -> None:
    with pytest.raises(ValueError, match="one comparable observation per source"):
        DataConfidenceService().assess(
            [
                _datum("same_source", 100.0, 90.0),
                _datum("same_source", 101.0, 90.0),
            ]
        )


def test_confidence_rejects_negative_discrepancy_threshold() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        DataConfidenceService().assess(
            [_datum("one", 100.0, 90.0)],
            discrepancy_threshold_pct=-1.0,
        )


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_confidence_rejects_non_finite_numeric_observations(
    invalid_value: float,
) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        DataConfidenceService().assess(
            [
                _datum("one", 100.0, 90.0),
                _datum("two", invalid_value, 90.0),
            ]
        )


@pytest.mark.parametrize(
    "invalid_threshold",
    [float("nan"), float("inf"), float("-inf"), True],
)
def test_confidence_rejects_non_finite_or_boolean_thresholds(
    invalid_threshold: float,
) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        DataConfidenceService().assess(
            [_datum("one", 100.0, 90.0)],
            discrepancy_threshold_pct=invalid_threshold,
        )
