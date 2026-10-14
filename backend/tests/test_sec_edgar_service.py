from typing import Any

import pytest

from app.services.sec_edgar_service import SecEdgarService


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None

    def get(self, url: str, headers: dict[str, str]) -> FakeResponse:
        self.last_url = url
        self.last_headers = headers
        return FakeResponse(self.payload)


def test_normalize_cik() -> None:
    assert SecEdgarService.normalize_cik("320193") == "0000320193"
    assert SecEdgarService.normalize_cik(1067983) == "0001067983"


def test_company_facts_uses_official_sec_endpoint() -> None:
    client = FakeClient({"entityName": "Apple Inc."})
    service = SecEdgarService(client=client, user_agent="ATHENA test contact@example.com")

    result = service.get_company_facts("320193")

    assert result["entityName"] == "Apple Inc."
    assert client.last_url == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )
    assert client.last_headers is not None
    assert "ATHENA test" in client.last_headers["User-Agent"]


def test_company_ticker_exchange_associations_normalize_sec_identity_data() -> None:
    client = FakeClient(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [320193, "Apple Inc.", "aapl", "Nasdaq"],
                [789019, "Microsoft Corp", "MSFT", "Nasdaq"],
                [None, "Invalid", "BAD", "NYSE"],
                [1045810, "NVIDIA CORP", "NVDA", "Nasdaq", "extra"],
            ],
        }
    )
    service = SecEdgarService(client=client, user_agent="ATHENA test contact@example.com")

    result = service.get_company_ticker_exchange_associations()

    assert client.last_url == "https://www.sec.gov/files/company_tickers_exchange.json"
    assert result == [
        {
            "cik": "0000320193",
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "exchange": "Nasdaq",
        },
        {
            "cik": "0000789019",
            "name": "Microsoft Corp",
            "ticker": "MSFT",
            "exchange": "Nasdaq",
        },
    ]


def test_company_ticker_exchange_associations_reject_incomplete_schema() -> None:
    client = FakeClient(
        {
            "fields": ["cik", "name", "ticker"],
            "data": [],
        }
    )
    service = SecEdgarService(client=client, user_agent="ATHENA test contact@example.com")

    with pytest.raises(ValueError, match="fields are incomplete"):
        service.get_company_ticker_exchange_associations()


def test_filter_institutional_and_insider_filings_preserves_publication_time() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["13F-HR", "4", "10-K", "13F-HR/A"],
                "accessionNumber": ["a", "b", "c", "d"],
                "filingDate": ["2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"],
                "reportDate": ["2026-06-30", "2026-08-15", "2026-06-30", "2026-06-30"],
                "acceptanceDateTime": [
                    "20260814163422",
                    "20260815121530",
                    "20260816110102",
                    "20260817174501",
                ],
                "primaryDocument": ["a.xml", "b.xml", "c.htm", "d.xml"],
            }
        }
    }
    client = FakeClient(payload)
    service = SecEdgarService(client=client, user_agent="ATHENA test contact@example.com")

    institutional = service.get_institutional_filings("1067983")
    insiders = service.get_insider_filings("320193")

    assert [item["form"] for item in institutional] == ["13F-HR", "13F-HR/A"]
    assert [item["form"] for item in insiders] == ["4"]
    assert institutional[0]["reportDate"] == "2026-06-30"
    assert institutional[0]["filingDate"] == "2026-08-14"
    assert institutional[0]["acceptanceDateTime"] == "20260814163422"
    assert institutional[1]["acceptanceDateTime"] == "20260817174501"
    assert insiders[0]["acceptanceDateTime"] == "20260815121530"
