from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.services.alpha_vantage_corporate_action_service import (
    AlphaVantageCorporateActionService,
)


NOW = datetime(2026, 9, 12, 11, 0, tzinfo=timezone.utc)


def _client(responses: dict[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        function = request.url.params.get("function")
        assert request.url.params.get("symbol") == "AAPL"
        assert request.url.params.get("apikey") == "test-secret-key"
        return httpx.Response(200, json=responses[function], request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_adapter_translates_dividends_and_splits_to_existing_pit_contract() -> None:
    client = _client(
        {
            "DIVIDENDS": {
                "symbol": "AAPL",
                "data": [
                    {"ex_dividend_date": "2026-08-10", "amount": "0.25"},
                    {"ex_dividend_date": "2027-01-10", "amount": "0.30"},
                ],
            },
            "SPLITS": {
                "symbol": "AAPL",
                "data": [
                    {"effective_date": "2026-07-01", "split_factor": "4:1"},
                ],
            },
        }
    )
    service = AlphaVantageCorporateActionService(
        api_key="test-secret-key",
        client=client,
        clock=lambda: NOW,
    )

    rows = service.get_history("aapl", from_date="2026-01-01", to_date="2026-12-31")

    assert len(rows) == 2
    assert rows[0] == {
        "symbol": "AAPL",
        "sourceProvider": "alpha_vantage",
        "timestamp": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "retrievedAt": NOW,
        "dividend": None,
        "stockSplit": 4.0,
    }
    assert rows[1]["timestamp"] == datetime(2026, 8, 10, tzinfo=timezone.utc)
    assert rows[1]["dividend"] == 0.25
    assert rows[1]["sourceProvider"] == "alpha_vantage"
    assert rows[1]["retrievedAt"] == NOW


def test_adapter_accepts_numeric_split_factor_and_inclusive_date_filter() -> None:
    client = _client(
        {
            "DIVIDENDS": {"data": []},
            "SPLITS": {
                "data": [
                    {"effective_date": "2026-08-01", "split_factor": "2.0"},
                    {"effective_date": "2026-08-02", "split_factor": "3.0"},
                ]
            },
        }
    )
    service = AlphaVantageCorporateActionService(
        api_key="test-secret-key",
        client=client,
        clock=lambda: NOW,
    )

    rows = service.get_history("AAPL", from_date="2026-08-02", to_date="2026-08-02")

    assert len(rows) == 1
    assert rows[0]["stockSplit"] == 3.0


def test_adapter_requires_external_key_without_leaking_a_secret(monkeypatch) -> None:
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    service = AlphaVantageCorporateActionService(api_key=None)

    with pytest.raises(RuntimeError) as exc_info:
        service.get_history("AAPL")

    assert "ALPHA_VANTAGE_API_KEY" in str(exc_info.value)
    assert "apikey=" not in str(exc_info.value)
    service.close()


def test_adapter_fails_closed_on_provider_information_response() -> None:
    client = _client(
        {
            "DIVIDENDS": {"Information": "rate limit or entitlement message"},
            "SPLITS": {"data": []},
        }
    )
    service = AlphaVantageCorporateActionService(
        api_key="test-secret-key",
        client=client,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.get_history("AAPL")

    assert "did not return corporate-action data" in str(exc_info.value)
    assert "test-secret-key" not in str(exc_info.value)


def test_adapter_rejects_non_finite_or_malformed_corporate_action_values() -> None:
    client = _client(
        {
            "DIVIDENDS": {
                "data": [{"ex_dividend_date": "2026-08-10", "amount": "NaN"}]
            },
            "SPLITS": {"data": []},
        }
    )
    service = AlphaVantageCorporateActionService(
        api_key="test-secret-key",
        client=client,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="finite and positive"):
        service.get_history("AAPL")
