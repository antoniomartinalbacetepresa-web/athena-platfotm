from datetime import datetime, timedelta, timezone

import pytest

from app.services.portfolio_correlation_service import PortfolioCorrelationService


class FakeObservationRepository:
    def __init__(self, rows_by_instrument):
        self.rows_by_instrument = rows_by_instrument
        self.calls = []

    def list_for_instrument(
        self,
        instrument_id,
        *,
        source_provider=None,
        knowledge_cutoff=None,
        observed_from=None,
        observed_to=None,
    ):
        self.calls.append(
            {
                "instrument_id": instrument_id,
                "source_provider": source_provider,
                "knowledge_cutoff": knowledge_cutoff,
                "observed_from": observed_from,
                "observed_to": observed_to,
            }
        )
        return list(self.rows_by_instrument[instrument_id])


def _rows(prices, *, retrieved_offset_minutes=1):
    start = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    result = []
    for index, price in enumerate(prices):
        observed = start + timedelta(days=index)
        retrieved = observed + timedelta(minutes=retrieved_offset_minutes)
        result.append(
            {
                "observed_at": observed.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "adjusted_close": price,
            }
        )
    return result


def test_portfolio_correlation_uses_pit_adjusted_returns_and_keeps_no_advice():
    repository = FakeObservationRepository(
        {
            10: _rows([100.0, 110.0, 121.0, 108.9]),
            20: _rows([200.0, 220.0, 242.0, 217.8]),
        }
    )
    service = PortfolioCorrelationService(observation_repository=repository)
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)

    result = service.calculate_pair(
        left_instrument_id=10,
        right_instrument_id=20,
        source_provider="yahoo_finance",
        knowledge_cutoff=cutoff,
    )

    assert result.sample_count == 3
    assert result.correlation == pytest.approx(1.0)
    assert result.source_provider == "yahoo_finance"
    assert result.knowledge_cutoff == cutoff.isoformat()
    assert len(repository.calls) == 2
    assert all(call["knowledge_cutoff"] == cutoff for call in repository.calls)
    payload = result.to_api_dict()
    assert payload["priceField"] == "adjusted_close"
    assert payload["recommendationPolicy"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["allocationInfluence"] is False
    assert payload["automaticTrading"] is False


def test_portfolio_correlation_propagates_requested_window_and_source():
    repository = FakeObservationRepository(
        {1: _rows([10.0, 11.0, 10.0]), 2: _rows([20.0, 18.0, 21.0])}
    )
    service = PortfolioCorrelationService(observation_repository=repository)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 5, tzinfo=timezone.utc)
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)

    service.calculate_pair(
        left_instrument_id=1,
        right_instrument_id=2,
        source_provider="verified_source",
        knowledge_cutoff=cutoff,
        observed_from=start,
        observed_to=end,
    )

    assert all(call["source_provider"] == "verified_source" for call in repository.calls)
    assert all(call["observed_from"] == start for call in repository.calls)
    assert all(call["observed_to"] == end for call in repository.calls)


def test_portfolio_correlation_fails_closed_without_adjusted_close():
    left = _rows([100.0, 101.0, 102.0])
    left[1]["adjusted_close"] = None
    repository = FakeObservationRepository({1: left, 2: _rows([50.0, 51.0, 52.0])})
    service = PortfolioCorrelationService(observation_repository=repository)

    with pytest.raises(ValueError, match="adjusted_close"):
        service.calculate_pair(
            left_instrument_id=1,
            right_instrument_id=2,
            source_provider="yahoo_finance",
            knowledge_cutoff=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )


def test_portfolio_correlation_fails_closed_for_insufficient_overlap_or_zero_variance():
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)
    insufficient = FakeObservationRepository(
        {1: _rows([100.0, 101.0]), 2: _rows([50.0, 51.0])}
    )
    with pytest.raises(ValueError, match="tres observaciones"):
        PortfolioCorrelationService(observation_repository=insufficient).calculate_pair(
            left_instrument_id=1,
            right_instrument_id=2,
            source_provider="yahoo_finance",
            knowledge_cutoff=cutoff,
        )

    flat_returns = FakeObservationRepository(
        {1: _rows([100.0, 110.0, 121.0]), 2: _rows([50.0, 55.0, 60.5])}
    )
    with pytest.raises(ValueError, match="sin varianza"):
        PortfolioCorrelationService(observation_repository=flat_returns).calculate_pair(
            left_instrument_id=1,
            right_instrument_id=2,
            source_provider="yahoo_finance",
            knowledge_cutoff=cutoff,
        )


def test_portfolio_correlation_rejects_identity_and_temporal_contract_violations():
    repository = FakeObservationRepository(
        {1: _rows([100.0, 101.0, 99.0]), 2: _rows([50.0, 52.0, 51.0])}
    )
    service = PortfolioCorrelationService(observation_repository=repository)
    cutoff = datetime(2026, 1, 10, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="distintos"):
        service.calculate_pair(
            left_instrument_id=1,
            right_instrument_id=1,
            source_provider="yahoo_finance",
            knowledge_cutoff=cutoff,
        )

    with pytest.raises(ValueError, match="zona horaria"):
        service.calculate_pair(
            left_instrument_id=1,
            right_instrument_id=2,
            source_provider="yahoo_finance",
            knowledge_cutoff=datetime(2026, 1, 10),
        )

    impossible = _rows([100.0, 101.0, 99.0])
    impossible[1]["retrieved_at"] = (
        datetime.fromisoformat(impossible[1]["observed_at"]) - timedelta(seconds=1)
    ).isoformat()
    bad_repository = FakeObservationRepository({1: impossible, 2: _rows([50.0, 52.0, 51.0])})
    with pytest.raises(ValueError, match="provenance temporal imposible"):
        PortfolioCorrelationService(observation_repository=bad_repository).calculate_pair(
            left_instrument_id=1,
            right_instrument_id=2,
            source_provider="yahoo_finance",
            knowledge_cutoff=cutoff,
        )
