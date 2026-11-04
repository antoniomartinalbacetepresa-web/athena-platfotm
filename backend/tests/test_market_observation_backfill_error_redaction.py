"""Provider and persistence errors must not leak credentials through backfill reports."""
from datetime import date

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.market_observation_backfill_service import MarketObservationBackfillService


class _Provider:
    PROVIDER_ID = "yahoo"

    def __init__(self, response):
        self.response = response

    def get_history(self, symbol, from_date=None, to_date=None):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _service(tmp_path, response):
    database = AthenaDatabase(tmp_path / "history.db")
    database.initialize()
    instrument_id = InstrumentRepository(database=database).upsert({
        "symbol": "AAA", "companyName": "AAA", "country": "United States",
        "regionKey": "america", "exchangeShortName": "TEST",
        "instrumentType": "common_stock",
    })
    service = MarketObservationBackfillService(
        database=database, history_provider=_Provider(response),
        today_provider=lambda: date(2026, 10, 31),
    )
    return service, database, instrument_id


def _run(service):
    return service.run(limit=1, from_date="2025-01-01", to_date="2025-01-03")


@pytest.mark.parametrize("error", [
    RuntimeError("provider URL https://secret.example/?api_key=DO_NOT_LOG"),
    ValueError("provider header Authorization: Bearer DO_NOT_LOG"),
])
def test_provider_exceptions_are_redacted_from_report_and_api(tmp_path, error):
    service, database, instrument_id = _service(tmp_path, error)
    report = _run(service)
    assert report.failed_count == 1
    assert report.failures[0]["error"] == "No se pudo consultar el proveedor histórico."
    assert "DO_NOT_LOG" not in str(report.to_api_dict())
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_untrusted_validation_value_is_not_reflected_in_failure(tmp_path):
    service, database, instrument_id = _service(tmp_path, [{
        "symbol": "DO_NOT_LOG", "sourceProvider": "yahoo",
        "timestamp": "2025-01-02T21:00:00+00:00", "close": 100.0,
    }])
    report = _run(service)
    assert report.failed_count == 1
    assert "símbolo declarado" in report.failures[0]["error"]
    assert "DO_NOT_LOG" not in str(report.to_api_dict())
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []


def test_persistence_exceptions_are_redacted_without_claiming_success(tmp_path, monkeypatch):
    service, database, instrument_id = _service(tmp_path, [{
        "symbol": "AAA", "sourceProvider": "yahoo",
        "timestamp": "2025-01-02T21:00:00+00:00", "close": 100.0,
    }])
    def failed_persistence(**kwargs):
        raise RuntimeError("sqlite path /private/DO_NOT_LOG or database credentials")
    monkeypatch.setattr(service._observations, "save_many", failed_persistence)
    report = _run(service)
    assert report.failed_count == 1
    assert report.persisted_instrument_count == 0
    assert report.observations_inserted == 0
    assert report.failures[0]["error"] == "No se pudo persistir el histórico validado."
    assert "DO_NOT_LOG" not in str(report.to_api_dict())
    assert MarketObservationRepository(database=database).list_for_instrument(instrument_id) == []
