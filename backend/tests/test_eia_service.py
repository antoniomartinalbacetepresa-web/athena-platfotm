import httpx
import pytest

from app.services.eia_service import EiaService


def test_eia_requires_api_key() -> None:
    service = EiaService(api_key="", client=httpx.Client())
    with pytest.raises(RuntimeError):
        service.get_data("petroleum/pri/spt")


def test_eia_builds_v2_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/petroleum/pri/spt/data/"
        assert request.url.params["api_key"] == "test-key"
        assert request.url.params["frequency"] == "weekly"
        assert request.url.params["data[0]"] == "value"
        return httpx.Response(200, json={"response": {"data": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = EiaService(api_key="test-key", client=client)
    result = service.get_data(
        "petroleum/pri/spt",
        data=["value"],
        frequency="weekly",
    )
    assert result["response"]["data"] == []
