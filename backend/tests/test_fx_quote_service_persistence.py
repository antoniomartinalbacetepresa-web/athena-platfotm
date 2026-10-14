from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.fx_rate_repository import FxRateRepository
from app.services.fx_quote_service import FxQuoteService


class FakeMarketService:
    def __init__(self, history):
        self.history = history
        self.history_calls = []

    def get_quote(self, symbol: str):
        raise AssertionError("Current quote is not expected in historical replay tests.")

    def get_history(self, symbol: str, from_date=None, to_date=None):
        self.history_calls.append(
            {"symbol": symbol, "from_date": from_date, "to_date": to_date}
        )
        return deepcopy(self.history)


def _repository(tmp_path) -> FxRateRepository:
    return FxRateRepository(AthenaDatabase(tmp_path / "athena-fx-replay.db"))


def _payload(*, retrieved_at: str = "2026-08-04T12:00:00+00:00"):
    return {
        "symbol": "USDEUR=X",
        "timestamp": "2026-08-03T00:00:00+00:00",
        "retrievedAt": retrieved_at,
        "sourceProvider": "yahoo",
        "close": 0.865,
    }


def test_historical_fx_is_persisted_then_replayed_without_upstream_call(tmp_path) -> None:
    repository = _repository(tmp_path)
    first_market = FakeMarketService([_payload()])
    cutoff = datetime(2026, 8, 4, 12, 5, tzinfo=timezone.utc)

    first = FxQuoteService(
        market_service=first_market,
        repository=repository,
    ).get_historical_rate(
        base_currency="USD",
        quote_currency="EUR",
        observed_on=date(2026, 8, 3),
        knowledge_cutoff=cutoff,
    )

    replay_market = FakeMarketService([])
    replay = FxQuoteService(
        market_service=replay_market,
        repository=repository,
    ).get_historical_rate(
        base_currency="USD",
        quote_currency="EUR",
        observed_on=date(2026, 8, 3),
        knowledge_cutoff=cutoff,
    )

    assert len(first_market.history_calls) == 1
    assert replay_market.history_calls == []
    assert first["replayedFromPersistence"] is False
    assert replay["replayedFromPersistence"] is True
    assert replay["rate"] == pytest.approx(first["rate"])
    assert replay["observedAt"] == first["observedAt"]
    assert replay["retrievedAt"] == first["retrievedAt"]
    assert replay["sourceProvider"] == "yahoo"
    assert replay["sourceSymbol"] == "USDEUR=X"
    assert replay["knowledgeCutoff"] == cutoff.isoformat()
    assert replay["policy"]["persistedReplayRequiresOriginalRetrievalBeforeCutoff"] is True


def test_historical_fx_does_not_replay_observation_unknown_at_cutoff(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save(
        observed_on=date(2026, 8, 3),
        base_currency="USD",
        quote_currency="EUR",
        rate=0.865,
        source_provider="yahoo",
        source_symbol="USDEUR=X",
        observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 9, 4, 13, tzinfo=timezone.utc),
    )
    market = FakeMarketService([_payload(retrieved_at="2026-09-04T13:00:00+00:00")])

    with pytest.raises(RuntimeError, match="lookahead"):
        FxQuoteService(
            market_service=market,
            repository=repository,
        ).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 3),
            knowledge_cutoff=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )

    assert len(market.history_calls) == 1


def test_historical_fx_rejects_requested_observation_after_cutoff_before_upstream(tmp_path) -> None:
    market = FakeMarketService([_payload()])

    with pytest.raises(RuntimeError, match="lookahead"):
        FxQuoteService(
            market_service=market,
            repository=_repository(tmp_path),
        ).get_historical_rate(
            base_currency="USD",
            quote_currency="EUR",
            observed_on=date(2026, 8, 5),
            knowledge_cutoff=datetime(2026, 8, 4, 23, 59, tzinfo=timezone.utc),
        )

    assert market.history_calls == []


def test_historical_identity_rejects_future_observation_date() -> None:
    market = FakeMarketService([])

    with pytest.raises(RuntimeError, match="lookahead"):
        FxQuoteService(market_service=market).get_historical_rate(
            base_currency="EUR",
            quote_currency="EUR",
            observed_on=date(2026, 8, 5),
            knowledge_cutoff=datetime(2026, 8, 4, 23, 59, tzinfo=timezone.utc),
        )

    assert market.history_calls == []
