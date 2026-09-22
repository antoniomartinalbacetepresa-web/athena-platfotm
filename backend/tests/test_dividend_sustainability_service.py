from datetime import datetime, timedelta, timezone

import pytest

from app.services.dividend_sustainability_service import DividendSustainabilityService


def _cutoff() -> datetime:
    return datetime(2026, 8, 2, tzinfo=timezone.utc)


def test_comparable_pit_fundamentals_compute_earnings_and_fcf_coverage() -> None:
    cutoff = _cutoff()
    result = DividendSustainabilityService.analyze(
        dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
        knowledge_cutoff=cutoff, source_provider="filing",
        retrieved_at=cutoff - timedelta(days=1), source_timestamp=cutoff - timedelta(days=2),
        comparable_window=True, currency_consistent=True,
    )
    assert result.earnings_payout_ratio == pytest.approx(0.40)
    assert result.fcf_payout_ratio == pytest.approx(0.50)
    assert result.earnings_covered is True and result.fcf_covered is True
    assert result.sustainability_score == pytest.approx(0.55)
    assert result.to_api_dict()["pitSafe"] is True


def test_post_cutoff_fundamentals_cannot_leak_into_sustainability() -> None:
    cutoff = _cutoff()
    result = DividendSustainabilityService.analyze(
        dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
        knowledge_cutoff=cutoff, source_provider="filing",
        retrieved_at=cutoff + timedelta(seconds=1), comparable_window=True, currency_consistent=True,
    )
    assert result.earnings_payout_ratio is None
    assert result.fcf_payout_ratio is None
    assert result.sustainability_score is None
    assert result.source_provider is None and result.retrieved_at is None


def test_source_timestamp_cannot_be_future_or_newer_than_retrieval() -> None:
    cutoff = _cutoff()
    cases = (
        (cutoff - timedelta(days=1), cutoff + timedelta(seconds=1)),
        (cutoff - timedelta(days=2), cutoff - timedelta(days=1)),
    )
    for retrieved_at, source_timestamp in cases:
        result = DividendSustainabilityService.analyze(
            dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
            knowledge_cutoff=cutoff, source_provider="filing",
            retrieved_at=retrieved_at, source_timestamp=source_timestamp,
            comparable_window=True, currency_consistent=True,
        )
        assert result.earnings_payout_ratio is None
        assert result.fcf_payout_ratio is None
        assert result.sustainability_score is None
        assert result.source_provider is None
        assert result.source_timestamp is None
        assert result.retrieved_at is None


def test_naive_provenance_timestamps_are_rejected() -> None:
    cutoff = _cutoff()
    with pytest.raises(ValueError, match="retrieved_at"):
        DividendSustainabilityService.analyze(
            dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
            knowledge_cutoff=cutoff, source_provider="filing",
            retrieved_at=datetime(2026, 8, 1), comparable_window=True, currency_consistent=True,
        )
    with pytest.raises(ValueError, match="source_timestamp"):
        DividendSustainabilityService.analyze(
            dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
            knowledge_cutoff=cutoff, source_provider="filing",
            retrieved_at=cutoff - timedelta(days=1), source_timestamp=datetime(2026, 7, 31),
            comparable_window=True, currency_consistent=True,
        )


def test_non_comparable_window_or_currency_fails_closed() -> None:
    cutoff = _cutoff()
    for comparable, currency_ok in ((False, True), (True, False)):
        result = DividendSustainabilityService.analyze(
            dividends_paid=40.0, net_income=100.0, free_cash_flow=80.0,
            knowledge_cutoff=cutoff, source_provider="filing", retrieved_at=cutoff,
            comparable_window=comparable, currency_consistent=currency_ok,
        )
        assert result.earnings_payout_ratio is None
        assert result.fcf_payout_ratio is None
        assert result.sustainability_score is None


def test_loss_and_negative_fcf_are_unknown_not_false_coverage() -> None:
    cutoff = _cutoff()
    result = DividendSustainabilityService.analyze(
        dividends_paid=40.0, net_income=-10.0, free_cash_flow=-5.0,
        knowledge_cutoff=cutoff, source_provider="filing", retrieved_at=cutoff,
        comparable_window=True, currency_consistent=True,
    )
    assert result.earnings_payout_ratio is None and result.earnings_covered is None
    assert result.fcf_payout_ratio is None and result.fcf_covered is None
    assert result.sustainability_score is None


def test_over_100_percent_payout_is_explicitly_uncovered() -> None:
    cutoff = _cutoff()
    result = DividendSustainabilityService.analyze(
        dividends_paid=120.0, net_income=100.0, free_cash_flow=80.0,
        knowledge_cutoff=cutoff, source_provider="filing", retrieved_at=cutoff,
        comparable_window=True, currency_consistent=True,
    )
    assert result.earnings_payout_ratio == pytest.approx(1.2)
    assert result.fcf_payout_ratio == pytest.approx(1.5)
    assert result.earnings_covered is False and result.fcf_covered is False
    assert result.sustainability_score == 0.0
