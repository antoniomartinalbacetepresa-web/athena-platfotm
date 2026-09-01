import pytest

from scripts import backfill_market_observations


class FakeReport:
    def to_api_dict(self):
        return {"status": "completed", "selectedCount": 2}


class FakeService:
    def __init__(self, *, progress_callback=None) -> None:
        self.progress_callback = progress_callback
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return FakeReport()


def test_backfill_script_uses_bounded_defaults() -> None:
    parser = backfill_market_observations.build_parser()
    args = parser.parse_args([])

    assert args.limit == 25
    assert args.offset == 0
    assert args.from_date is None
    assert args.to_date is None
    assert backfill_market_observations.MAX_LIMIT == 500


def test_backfill_script_rejects_unbounded_batch() -> None:
    with pytest.raises(ValueError, match="no puede superar"):
        backfill_market_observations.run(
            limit=501,
            offset=0,
            from_date=None,
            to_date=None,
        )


def test_backfill_script_forwards_dates_and_pagination(monkeypatch) -> None:
    fake = FakeService()
    monkeypatch.setattr(
        backfill_market_observations,
        "MarketObservationBackfillService",
        lambda progress_callback=None: fake,
    )

    report = backfill_market_observations.run(
        limit=10,
        offset=20,
        from_date="2025-01-01",
        to_date="2026-01-01",
    )

    assert report == {"status": "completed", "selectedCount": 2}
    assert fake.calls == [
        {
            "limit": 10,
            "offset": 20,
            "from_date": "2025-01-01",
            "to_date": "2026-01-01",
        }
    ]
