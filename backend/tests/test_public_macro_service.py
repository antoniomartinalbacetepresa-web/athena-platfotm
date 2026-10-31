from typing import Any

from app.services.public_macro_service import PublicMacroService


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.last_url: str | None = None
        self.last_params: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.last_url = url
        self.last_params = params
        self.last_headers = headers
        return FakeResponse(self.payload)


def test_world_bank_indicator_builds_v2_json_query() -> None:
    client = FakeClient([
        {"page": 1, "pages": 1},
        [{"countryiso3code": "USA", "date": "2025", "value": 1.0}],
    ])
    service = PublicMacroService(client=client)

    result = service.get_world_bank_indicator(
        country="US",
        indicator="NY.GDP.MKTP.CD",
        start_year=2020,
        end_year=2025,
    )

    assert result["observations"][0]["countryiso3code"] == "USA"
    assert client.last_url == (
        "https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.CD"
    )
    assert client.last_params is not None
    assert client.last_params["format"] == "json"
    assert client.last_params["date"] == "2020:2025"


def test_ecb_series_uses_official_sdmx_endpoint() -> None:
    client = FakeClient({"data": {"dataSets": []}})
    service = PublicMacroService(client=client)

    result = service.get_ecb_series(
        flow_ref="EXR",
        key="M.USD.EUR.SP00.A",
        last_n_observations=2,
    )

    assert result == {"data": {"dataSets": []}}
    assert client.last_url == (
        "https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A"
    )
    assert client.last_params is not None
    assert client.last_params["format"] == "jsondata"
    assert client.last_params["lastNObservations"] == 2
    assert client.last_headers is not None
    assert "sdmx.data+json" in client.last_headers["Accept"]
