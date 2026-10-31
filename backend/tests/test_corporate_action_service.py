from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.corporate_action_service import CorporateActionService
from app.services.yahoo_market_service import YahooMarketService


def _history_observation(
    *,
    timestamp: str = "2026-01-15T00:00:00+00:00",
    retrieved_at: str = "2026-09-11T06:00:00+00:00",
    dividend: float | None = None,
    stock_split: float | None = None,
) -> dict[str, object]:
    return {
        "symbol": "aapl",
        "timestamp": timestamp,
        "retrievedAt": retrieved_at,
        "sourceProvider": "yahoo",
        "dividend": dividend,
        "stockSplit": stock_split,
    }


def test_extracts_dividend_and_split_with_provenance() -> None:
    service = CorporateActionService()

    actions = service.extract_from_history(
        [
            _history_observation(
                dividend=0.25,
                stock_split=4.0,
            )
        ]
    )

    assert len(actions) == 2
    assert actions[0].symbol == "AAPL"
    assert {item.action_type for item in actions} == {
        "dividend",
        "stock_split",
    }
    assert {item.source_provider for item in actions} == {"yahoo"}


def test_zero_values_do_not_create_actions() -> None:
    service = CorporateActionService()

    actions = service.extract_from_history(
        [_history_observation(dividend=0.0, stock_split=0.0)]
    )

    assert actions == ()


def test_rejects_retrieval_before_observation() -> None:
    service = CorporateActionService()

    with pytest.raises(
        ValueError,
        match="retrievedAt no puede ser anterior",
    ):
        service.extract_from_history(
            [
                _history_observation(
                    timestamp="2026-09-12T00:00:00+00:00",
                    retrieved_at="2026-09-11T06:00:00+00:00",
                    dividend=0.25,
                )
            ]
        )


def test_point_in_time_filter_blocks_retrospective_leakage() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history(
        [
            _history_observation(
                timestamp="2026-01-15T00:00:00+00:00",
                retrieved_at="2026-09-11T06:00:00+00:00",
                stock_split=4.0,
            )
        ]
    )

    before_retrieval = service.visible_as_of(
        actions,
        knowledge_cutoff=datetime(
            2026,
            6,
            1,
            tzinfo=timezone.utc,
        ),
    )
    after_retrieval = service.visible_as_of(
        actions,
        knowledge_cutoff=datetime(
            2026,
            9,
            11,
            7,
            tzinfo=timezone.utc,
        ),
    )

    assert before_retrieval == ()
    assert len(after_retrieval) == 1


def test_cumulative_split_factor_uses_only_visible_symbol_actions() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history(
        [
            _history_observation(stock_split=4.0),
            {
                **_history_observation(stock_split=2.0),
                "symbol": "MSFT",
            },
        ]
    )

    factor = service.cumulative_split_factor(
        actions,
        symbol="aapl",
        knowledge_cutoff=datetime(
            2026,
            9,
            11,
            7,
            tzinfo=timezone.utc,
        ),
    )

    assert factor == 4.0


def test_yahoo_history_defaults_to_one_year_and_preserves_actions(
    monkeypatch,
) -> None:
    service = YahooMarketService()
    calls: list[dict[str, object]] = []
    frame = pd.DataFrame(
        [
            {
                "Open": 100.0,
                "High": 102.0,
                "Low": 99.0,
                "Close": 101.0,
                "Adj Close": 100.5,
                "Volume": 1000,
                "Dividends": 0.25,
                "Stock Splits": 4.0,
            }
        ],
        index=pd.DatetimeIndex(["2026-01-15T00:00:00+00:00"]),
    )

    class FakeTicker:
        def history(self, **kwargs):
            calls.append(kwargs)
            return frame

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_history("aapl")

    assert calls == [
        {
            "start": None,
            "end": None,
            "period": "1y",
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
        }
    ]
    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["dividend"] == 0.25
    assert result[0]["stockSplit"] == 4.0


def test_yahoo_history_keeps_explicit_date_range_without_period(
    monkeypatch,
) -> None:
    service = YahooMarketService()
    calls: list[dict[str, object]] = []
    frame = pd.DataFrame(
        [
            {
                "Open": 100.0,
                "High": 102.0,
                "Low": 99.0,
                "Close": 101.0,
                "Adj Close": 101.0,
                "Volume": 1000,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            }
        ],
        index=pd.DatetimeIndex(["2025-01-01T00:00:00+00:00"]),
    )

    class FakeTicker:
        def history(self, **kwargs):
            calls.append(kwargs)
            return frame

    monkeypatch.setattr(
        "app.services.yahoo_market_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service.get_history(
        "AAPL",
        from_date="2025-01-01",
        to_date="2026-01-01",
    )

    assert calls[0]["period"] is None
    assert calls[0]["start"] == "2025-01-01"
    assert calls[0]["end"] == "2026-01-02"
    assert result[0]["dividend"] is None
    assert result[0]["stockSplit"] is None



def test_split_factor_counts_independent_matching_providers_once() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history([
        _history_observation(stock_split=4.0),
        {**_history_observation(stock_split=4.0), "sourceProvider": "alpha_vantage"},
    ])
    factor = service.cumulative_split_factor(
        actions, symbol="AAPL",
        knowledge_cutoff=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
    )
    assert factor == 4.0


def test_split_factor_quarantines_conflicting_provider_ratios() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history([
        _history_observation(stock_split=4.0),
        {**_history_observation(stock_split=2.0), "sourceProvider": "alpha_vantage"},
    ])
    with pytest.raises(ValueError, match="incompatibles"):
        service.cumulative_split_factor(
            actions, symbol="AAPL",
            knowledge_cutoff=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
        )


def test_split_factor_quarantines_same_provider_same_day_duplicates() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history([
        _history_observation(stock_split=4.0),
        _history_observation(timestamp="2026-01-15T12:00:00+00:00", stock_split=4.0),
    ])
    with pytest.raises(ValueError, match="duplicados"):
        service.cumulative_split_factor(
            actions, symbol="AAPL",
            knowledge_cutoff=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
        )


def test_split_factor_multiplies_distinct_economic_days() -> None:
    service = CorporateActionService()
    actions = service.extract_from_history([
        _history_observation(stock_split=4.0),
        _history_observation(timestamp="2026-02-15T00:00:00+00:00", stock_split=2.0),
    ])
    assert service.cumulative_split_factor(
        actions, symbol="AAPL",
        knowledge_cutoff=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
    ) == 8.0


@pytest.mark.parametrize("ratio", [0.0, -2.0, float("nan"), float("inf")])
def test_split_factor_rejects_invalid_ratios_even_in_direct_objects(ratio: float) -> None:
    from dataclasses import replace
    service = CorporateActionService()
    action = service.extract_from_history([_history_observation(stock_split=4.0)])[0]
    with pytest.raises(ValueError, match="finito y positivo"):
        service.cumulative_split_factor(
            [replace(action, value=ratio)], symbol="AAPL",
            knowledge_cutoff=datetime(2026, 9, 11, 7, tzinfo=timezone.utc),
        )
