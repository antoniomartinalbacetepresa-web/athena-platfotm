from __future__ import annotations

import httpx
import pytest

from app.services.cftc_cot_service import CftcCotService


def test_cftc_cot_builds_public_reporting_query() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[{"market_and_exchange_names": "TEST"}])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = CftcCotService(client=client)

    rows = service.get_rows(
        "tff_futures",
        limit=25,
        where="report_date_as_yyyy_mm_dd >= '2026-01-01'",
        order="report_date_as_yyyy_mm_dd DESC",
    )

    assert rows[0]["market_and_exchange_names"] == "TEST"
    url = str(captured["url"])
    assert "/resource/gpe5-46if.json" in url
    assert "%24limit=25" in url
    assert "%24where=" in url
    assert "%24order=" in url


def test_cftc_rejects_unknown_dataset() -> None:
    service = CftcCotService()
    with pytest.raises(ValueError, match="Unsupported CFTC"):
        service.get_rows("unknown")
    service.close()
