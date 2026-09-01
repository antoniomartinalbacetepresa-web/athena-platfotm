from typing import Any

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


def test_filter_institutional_and_insider_filings() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["13F-HR", "4", "10-K", "13F-HR/A"],
                "accessionNumber": ["a", "b", "c", "d"],
                "filingDate": ["2026-08-14", "2026-08-15", "2026-08-16", "2026-08-17"],
                "reportDate": ["2026-06-30", "2026-08-15", "2026-06-30", "2026-06-30"],
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
