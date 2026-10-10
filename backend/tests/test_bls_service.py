import httpx
import pytest

from app.services.bls_service import BlsService


def test_bls_series_posts_normalized_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        payload = __import__("json").loads(request.content)
        assert payload["seriesid"] == ["LNS14000000"]
        assert payload["startyear"] == "2024"
        assert payload["endyear"] == "2026"
        return httpx.Response(
            200,
            json={"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = BlsService(client=client)
    result = service.get_series([" LNS14000000 "], 2026, 2024)
    assert result["status"] == "REQUEST_SUCCEEDED"


def test_bls_optional_features_require_registration_key() -> None:
    service = BlsService(registration_key="", client=httpx.Client())
    with pytest.raises(RuntimeError):
        service.get_series(["LNS14000000"], catalog=True)
