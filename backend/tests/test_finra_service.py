import httpx
import pytest

from app.services.finra_service import FinraService


def test_finra_mock_short_interest_can_be_queried_without_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/consolidatedShortInterestMock")
        assert request.url.params["limit"] == "5"
        assert request.headers["accept"] == "application/json"
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = FinraService(access_token="", client=client)
    result = service.get_consolidated_short_interest(limit=5, mock=True)
    assert result == []


def test_finra_filtered_production_query_requires_token() -> None:
    service = FinraService(access_token="", client=httpx.Client())
    with pytest.raises(RuntimeError):
        service.get_consolidated_short_interest(symbol="AAPL")
