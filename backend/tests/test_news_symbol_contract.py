"""The company-news research route must reject malformed instrument identifiers.

Validation occurs before any external news provider is invoked.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_company_news_rejects_backslash_in_symbol() -> None:
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Microsoft", "symbol": r"MS\\FT"},
    )
    assert response.status_code == 422


def test_company_news_rejects_path_separator_in_symbol() -> None:
    response = TestClient(app).get(
        "/api/v1/news/company-evidence",
        params={"companyName": "Microsoft", "symbol": "MS/FT"},
    )
    assert response.status_code == 422
