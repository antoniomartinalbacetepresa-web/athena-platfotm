from datetime import date, datetime, timezone

import httpx
import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.twelve_data_history_service import (
    TwelveDataHistoryError,
    TwelveDataHistoryService,
)


SELECTION = {
    "symbol": "AAPL", "mic": "XNAS", "currency": "USD",
    "exchange_timezone": "America/New_York",
    "start": date(2026, 11, 23), "end": date(2026, 11, 25), "limit": 3,
}
NOW = datetime(2026, 11, 26, 15, tzinfo=timezone.utc)


def synthetic_payload():
    return {
        "status": "ok",
        "meta": {
            "symbol": "AAPL", "mic_code": "XNAS", "currency": "USD",
            "exchange_timezone": "America/New_York", "interval": "1day",
        },
        "values": [
            {"datetime": day, "open": "101", "high": "104", "low": "99",
             "close": "102", "volume": "200"}
            for day in ("2026-11-25", "2026-11-23")
        ],
    }


def history(handler, **selection):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = TwelveDataHistoryService(client, api_key="synthetic-key", clock=lambda: NOW)
        return service.get_history(**(SELECTION | selection))


def test_requests_exact_market_and_returns_ordered_unverified_sessions():
    def respond(request):
        assert request.url.host == "api.twelvedata.com"
        assert request.url.path == "/time_series"
        assert request.headers["Authorization"] == "apikey synthetic-key"
        assert dict(request.url.params) == {
            "symbol": "AAPL", "mic_code": "XNAS", "interval": "1day",
            "start_date": "2026-11-23", "end_date": "2026-11-25",
            "outputsize": "3", "adjust": "none",
        }
        return httpx.Response(200, json=synthetic_payload())

    rows = history(respond)
    assert [row["sessionDate"] for row in rows] == ["2026-11-23", "2026-11-25"]
    assert rows[0]["sourceProvider"] == "twelve_data"
    assert rows[0]["retrievedAt"] == NOW.isoformat()
    assert rows[0]["volume"] == 200
    assert rows[0]["close"] == 102
    assert all(row["historicalPointInTimeEligible"] is False for row in rows)
    assert all("availableAt" not in row and "licenseRef" not in row for row in rows)


@pytest.mark.parametrize(("field", "value"), [
    ("open", True), ("close", "NaN"), ("low", "0"), ("high", "100"),
    ("volume", "0.5"), ("volume", "-1"), ("volume", "Infinity"),
    ("datetime", "2026-11-22"), ("datetime", "2026-11-26"),
    ("datetime", "2026-11-25T00:00:00"), ("datetime", "2026-11-23"),
])
def test_rejects_invalid_or_duplicate_bars(field, value):
    payload = synthetic_payload()
    payload["values"][0][field] = value
    with pytest.raises(TwelveDataHistoryError):
        history(lambda _: httpx.Response(200, json=payload), end=NOW.date())


@pytest.mark.parametrize(("field", "value"), [
    ("mic_code", "XNYS"), ("currency", "EUR"), ("symbol", "MSFT"),
    ("exchange_timezone", "UTC"), ("interval", "1min"),
])
def test_rejects_another_market_identity(field, value):
    payload = synthetic_payload()
    payload["meta"][field] = value
    with pytest.raises(TwelveDataHistoryError, match="identity mismatch"):
        history(lambda _: httpx.Response(200, json=payload))


@pytest.mark.parametrize("limit", [True, 0, 5001])
def test_validates_limit_before_provider_call(limit):
    with pytest.raises(TwelveDataHistoryError, match="limit"):
        history(lambda _: pytest.fail("provider should not be called"), limit=limit)


@pytest.mark.parametrize(("status", "payload", "message"), [
    (429, {}, "rate limit"),
    (200, {"status": "error", "code": 429, "message": "synthetic-key"}, "rate limit"),
    (403, {"message": "synthetic-key"}, "rejected"),
    (302, {}, "rejected"),
])
def test_provider_errors_are_sanitized(status, payload, message):
    with pytest.raises(TwelveDataHistoryError, match=message) as result:
        history(lambda _: httpx.Response(status, json=payload))
    assert "synthetic-key" not in str(result.value)


def test_rejects_payload_larger_than_requested_limit():
    with pytest.raises(TwelveDataHistoryError, match="row count"):
        history(lambda _: httpx.Response(200, json=synthetic_payload()), limit=1)


def test_transport_error_does_not_include_provider_details():
    def fail(request):
        raise httpx.ReadTimeout("synthetic-key", request=request)

    with pytest.raises(TwelveDataHistoryError, match="request failed") as result:
        history(fail)
    assert "synthetic-key" not in str(result.value)


def test_missing_credentials_fail_before_network_access():
    def unexpected_request(_):
        pytest.fail("provider should not be called")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        service = TwelveDataHistoryService(client, api_key="")
        with pytest.raises(TwelveDataHistoryError, match="key is missing"):
            service.get_history(**SELECTION)


def test_synthetic_twelve_data_preview_cannot_enter_pit_storage(tmp_path):
    database = AthenaDatabase(tmp_path / "synthetic_market.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAPL",
        "companyName": "Synthetic pilot fixture",
        "exchangeShortName": "NASDAQ",
        "instrumentType": "common_stock",
        "currency": "USD",
    })
    repository = MarketObservationRepository(database=database)
    rows = history(lambda _: httpx.Response(200, json=synthetic_payload()))
    # Simulate a future bridge that maps session dates to timestamps. Even
    # with compatible timestamps the provider refuses PIT eligibility.
    rows = [
        {**row, "timestamp": f"{row['sessionDate']}T21:00:00+00:00"}
        for row in rows
    ]
    synthetic_control = {"timestamp": "2026-11-20T21:00:00+00:00", "close": 100}

    def save(observations):
        return repository.save_many(
            instrument_id=instrument_id,
            observations=observations,
            source_provider="synthetic_twelve_data_fixture",
            retrieved_at=NOW,
        )

    with pytest.raises(ValueError, match="almacenamiento PIT"):
        save([synthetic_control, *rows])
    assert repository.list_for_instrument(instrument_id) == []

    assert save([synthetic_control]).inserted == 1
    assert save([synthetic_control]).unchanged == 1
    assert len(repository.list_for_instrument(instrument_id)) == 1
