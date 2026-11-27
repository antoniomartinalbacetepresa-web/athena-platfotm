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


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [
    "1_0_1", "١٠١", "１０１", " 101", "101 ", "\t101", "101\n", "101\u00a0",
])
def test_ohlcv_rejects_python_only_numeric_spellings(field, value):
    payload = synthetic_payload()
    # Every spelling denotes 101 in Python's permissive conversion routines.
    # Equal OHLC prices isolate lexical rejection from the range validator.
    payload["values"][0].update({name: "101" for name in ("open", "high", "low", "close")})
    payload["values"][0][field] = value
    with pytest.raises(TwelveDataHistoryError, match="OHLCV"):
        history(lambda _: httpx.Response(200, json=payload))


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [True, False, None, [], {}, "", "0x65", "1,01", "101\x00"])
def test_ohlcv_requires_a_json_number_or_ascii_decimal_string(field, value):
    payload = synthetic_payload()
    payload["values"][0][field] = value
    with pytest.raises(TwelveDataHistoryError):
        history(lambda _: httpx.Response(200, json=payload))


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_ohlcv_fields_are_required(field):
    payload = synthetic_payload()
    payload["values"][0].pop(field)
    with pytest.raises(TwelveDataHistoryError, match="OHLCV"):
        history(lambda _: httpx.Response(200, json=payload))


@pytest.mark.parametrize("value,expected", [
    (101, 101.0), (101.0, 101.0), ("101", 101.0), ("+101", 101.0),
    ("00101.000", 101.0), ("101.", 101.0), ("1.01e2", 101.0),
    ("1E+2", 100.0), (".101", .101), ("+.101", .101), ("1e-3", .001),
])
def test_prices_preserve_reasonable_ascii_decimal_and_exponent_formats(value, expected):
    payload = synthetic_payload()
    payload["values"][0].update({field: value for field in ("open", "high", "low", "close")})
    rows = history(lambda _: httpx.Response(200, json=payload))
    assert all(rows[-1][field] == expected for field in ("open", "high", "low", "close"))
    assert rows[-1]["historicalPointInTimeEligible"] is False


@pytest.mark.parametrize("value,expected", [
    (200, 200), (200.0, 200), ("200", 200), ("200.0", 200),
    ("+200", 200), ("00200", 200), ("200.", 200), ("2e2", 200),
    (".0", 0), ("0E-8", 0), (-0.0, 0),
    (str(2**63 - 1), 2**63 - 1), ("9223372036854775807.0", 2**63 - 1),
])
def test_integral_volume_preserves_ascii_formats_and_signed_64_bit_boundary(value, expected):
    payload = synthetic_payload()
    payload["values"][0]["volume"] = value
    rows = history(lambda _: httpx.Response(200, json=payload))
    assert rows[-1]["volume"] == expected
    assert type(rows[-1]["volume"]) is int


@pytest.mark.parametrize("value", ["200.5", "2e-1", "9223372036854775808", "9.223372036854775808e18"])
def test_volume_still_rejects_fractional_or_overflow_values(value):
    payload = synthetic_payload()
    payload["values"][0]["volume"] = value
    with pytest.raises(TwelveDataHistoryError, match="volume"):
        history(lambda _: httpx.Response(200, json=payload))


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


@pytest.mark.parametrize("eligibility", [False, None, 0, "true", 1])
def test_explicit_non_boolean_pit_eligibility_rolls_back_batch(tmp_path, eligibility):
    database = AthenaDatabase(tmp_path / "synthetic_eligibility.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAPL",
        "companyName": "Synthetic eligibility fixture",
        "exchangeShortName": "NASDAQ",
        "instrumentType": "common_stock",
        "currency": "USD",
    })
    repository = MarketObservationRepository(database=database)
    control = {"timestamp": "2026-11-20T21:00:00+00:00", "close": 100}
    rejected = {
        "timestamp": "2026-11-23T21:00:00+00:00",
        "close": 102,
        "historicalPointInTimeEligible": eligibility,
    }
    with pytest.raises(ValueError, match="almacenamiento PIT"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[control, rejected],
            source_provider="synthetic_eligibility_fixture",
            retrieved_at=NOW,
        )
    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize("provider", ["twelve_data", "Twelve-Data", "TWELVE DATA"])
def test_twelve_data_source_cannot_be_saved_without_pit_flag(tmp_path, provider):
    database = AthenaDatabase(tmp_path / "synthetic_provider_guard.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAPL", "companyName": "Synthetic source fixture",
        "exchangeShortName": "NASDAQ", "instrumentType": "common_stock",
        "currency": "USD",
    })
    repository = MarketObservationRepository(database=database)
    with pytest.raises(ValueError, match="Twelve Data"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[{"timestamp": "2026-11-23T21:00:00+00:00", "close": 102}],
            source_provider=provider, retrieved_at=NOW,
        )
    assert repository.list_for_instrument(instrument_id) == []


def test_twelve_data_row_cannot_be_relabelled_as_synthetic_pit(tmp_path):
    database = AthenaDatabase(tmp_path / "synthetic_relabel_guard.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAPL", "companyName": "Synthetic relabel fixture",
        "exchangeShortName": "NASDAQ", "instrumentType": "common_stock",
        "currency": "USD",
    })
    repository = MarketObservationRepository(database=database)
    with pytest.raises(ValueError, match="Twelve Data"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[
                {"timestamp": "2026-11-20T21:00:00+00:00", "close": 100},
                {"timestamp": "2026-11-23T21:00:00+00:00", "close": 102,
                 "sourceProvider": "twelve_data", "historicalPointInTimeEligible": True},
            ],
            source_provider="synthetic_relabel_fixture", retrieved_at=NOW,
        )
    assert repository.list_for_instrument(instrument_id) == []


@pytest.mark.parametrize("source_field", ["sourceProvider", "source_provider"])
@pytest.mark.parametrize("provider", ["twelve_data", "%74welve_data", "&#116;welve_data"])
def test_imported_twelve_data_provenance_cannot_be_laundered_by_field_name(
    tmp_path, source_field, provider
):
    """Both API and database-style provenance spellings must fail atomically."""
    database = AthenaDatabase(tmp_path / "synthetic_imported_provenance.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAPL", "companyName": "Synthetic imported fixture",
        "exchangeShortName": "NASDAQ", "instrumentType": "common_stock",
        "currency": "USD",
    })
    repository = MarketObservationRepository(database=database)
    with pytest.raises(ValueError, match="Twelve Data"):
        repository.save_many(
            instrument_id=instrument_id,
            observations=[
                {"timestamp": "2026-11-20T21:00:00+00:00", "close": 100},
                {"timestamp": "2026-11-23T21:00:00+00:00", "close": 102,
                 source_field: provider},
            ],
            source_provider="synthetic_imported_fixture",
            retrieved_at=NOW,
        )
    assert repository.list_for_instrument(instrument_id) == []
