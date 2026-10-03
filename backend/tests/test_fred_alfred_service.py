from __future__ import annotations

import httpx
import pytest

from app.services.fred_alfred_service import FredAlfredService


def test_fred_observations_preserve_vintage_parameters() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"observations": [{"date": "2020-01-01", "value": "1.0"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = FredAlfredService(api_key="test-key", client=client)

    payload = service.get_observations(
        "gdp",
        observation_start="2020-01-01",
        vintage_dates=("2020-02-01", "2020-03-01"),
    )

    assert payload["observations"][0]["value"] == "1.0"
    url = str(captured["url"])
    assert "series_id=GDP" in url
    assert "api_key=test-key" in url
    assert "observation_start=2020-01-01" in url
    assert "vintage_dates=2020-02-01%2C2020-03-01" in url


def test_fred_requires_backend_api_key() -> None:
    service = FredAlfredService(api_key="")
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        service.get_observations("GDP")
    service.close()


def test_alfred_vintage_dates_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={"vintage_dates": ["2020-01-01"]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = FredAlfredService(api_key="test-key", client=client)

    payload = service.get_vintage_dates("CPIAUCSL")

    assert captured["path"].endswith("/fred/series/vintagedates")
    assert payload["vintage_dates"] == ["2020-01-01"]
