import pytest

from app.models.normalized_data import DataProvenance, NormalizedDatum
from app.services.point_in_time_data_service import PointInTimeDataService


def _provenance(*, available_at: str | None) -> DataProvenance:
    return DataProvenance(
        source_id="official_source",
        retrieved_at="2026-09-01T10:00:00+00:00",
        effective_at="2026-06-30",
        published_at="2026-08-01T12:00:00+00:00",
        available_at=available_at,
    )


def test_point_in_time_requires_explicit_availability_timestamp() -> None:
    result = PointInTimeDataService().evaluate(
        _provenance(available_at=None),
        as_of="2026-08-15T00:00:00+00:00",
    )

    assert result.available is False
    assert result.reason == "explicit_availability_timestamp_required"
    assert result.available_at is None
    assert result.to_api_dict()["policy"] == "explicit_available_at_only"


def test_point_in_time_accepts_only_data_known_by_as_of() -> None:
    service = PointInTimeDataService()

    known = service.evaluate(
        _provenance(available_at="2026-08-01T12:00:00Z"),
        as_of="2026-08-01T12:00:00+00:00",
    )
    future = service.evaluate(
        _provenance(available_at="2026-08-01T12:00:01+00:00"),
        as_of="2026-08-01T12:00:00+00:00",
    )

    assert known.available is True
    assert known.reason == "available_at_or_before_as_of"
    assert future.available is False
    assert future.reason == "available_after_as_of"


def test_point_in_time_filter_excludes_unknown_and_future_data() -> None:
    data = [
        NormalizedDatum(
            metric="known",
            value=1,
            data_kind="fact",
            provenance=_provenance(available_at="2026-08-01T00:00:00+00:00"),
        ),
        NormalizedDatum(
            metric="future",
            value=2,
            data_kind="fact",
            provenance=_provenance(available_at="2026-09-01T00:00:00+00:00"),
        ),
        NormalizedDatum(
            metric="unknown",
            value=3,
            data_kind="fact",
            provenance=_provenance(available_at=None),
        ),
    ]

    filtered = PointInTimeDataService().filter_available(
        data,
        as_of="2026-08-15T00:00:00+00:00",
    )

    assert [datum.metric for datum in filtered] == ["known"]


def test_point_in_time_rejects_naive_or_invalid_timestamps() -> None:
    service = PointInTimeDataService()

    with pytest.raises(ValueError, match="timezone offset"):
        service.evaluate(
            _provenance(available_at="2026-08-01T12:00:00+00:00"),
            as_of="2026-08-15T00:00:00",
        )

    with pytest.raises(ValueError, match="ISO-8601"):
        service.evaluate(
            _provenance(available_at="not-a-date"),
            as_of="2026-08-15T00:00:00+00:00",
        )
