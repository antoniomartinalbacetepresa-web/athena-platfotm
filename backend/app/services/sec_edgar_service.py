from __future__ import annotations

import os
from typing import Any, Iterable

import httpx


class SecEdgarService:
    """Backend-only connector for public SEC EDGAR data APIs."""

    _BASE_URL = "https://data.sec.gov"
    _FILES_BASE_URL = "https://www.sec.gov/files"

    def __init__(
        self,
        client: httpx.Client | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=20.0)
        self._user_agent = (
            user_agent
            or os.getenv("ATHENA_SEC_USER_AGENT")
            or "ATHENA-TYCHE research-client"
        ).strip()

    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        normalized_cik = self.normalize_cik(cik)
        return self._get_json(
            f"{self._BASE_URL}/submissions/CIK{normalized_cik}.json"
        )

    def get_company_facts(self, cik: str | int) -> dict[str, Any]:
        normalized_cik = self.normalize_cik(cik)
        return self._get_json(
            f"{self._BASE_URL}/api/xbrl/companyfacts/CIK{normalized_cik}.json"
        )

    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        """Returns SEC-published CIK/ticker/name/exchange associations.

        The SEC describes this file as periodically updated search-assistance
        data and does not guarantee complete accuracy or scope. ATHENA should
        therefore treat it as strong identity evidence for covered SEC filers,
        not as a complete global issuer master.
        """

        payload = self._get_json(
            f"{self._FILES_BASE_URL}/company_tickers_exchange.json"
        )
        fields = payload.get("fields")
        data = payload.get("data")
        if not isinstance(fields, list) or not isinstance(data, list):
            raise ValueError("Unexpected SEC ticker association format.")

        normalized_fields = [str(field).strip() for field in fields]
        required = {"cik", "name", "ticker", "exchange"}
        if not required.issubset(set(normalized_fields)):
            raise ValueError("SEC ticker association fields are incomplete.")

        result: list[dict[str, str]] = []
        for values in data:
            if not isinstance(values, list) or len(values) != len(normalized_fields):
                continue
            record = dict(zip(normalized_fields, values, strict=True))
            ticker = str(record.get("ticker") or "").strip().upper()
            name = str(record.get("name") or "").strip()
            exchange = str(record.get("exchange") or "").strip()
            cik_value = record.get("cik")
            if not ticker or not name or cik_value in (None, ""):
                continue
            result.append(
                {
                    "cik": self.normalize_cik(cik_value),
                    "name": name,
                    "ticker": ticker,
                    "exchange": exchange,
                }
            )

        return result

    def get_recent_filings(
        self,
        cik: str | int,
        forms: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        submissions = self.get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})

        form_filter = {
            form.strip().upper()
            for form in (forms or [])
            if form.strip()
        }

        forms_data = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])

        result: list[dict[str, Any]] = []
        for index, form in enumerate(forms_data):
            normalized_form = str(form).upper()
            if form_filter and normalized_form not in form_filter:
                continue

            result.append(
                {
                    "form": form,
                    "accessionNumber": self._value_at(accession_numbers, index),
                    "filingDate": self._value_at(filing_dates, index),
                    "reportDate": self._value_at(report_dates, index),
                    "primaryDocument": self._value_at(primary_documents, index),
                }
            )

        return result

    def get_institutional_filings(self, cik: str | int) -> list[dict[str, Any]]:
        return self.get_recent_filings(
            cik,
            forms=("13F-HR", "13F-HR/A"),
        )

    def get_insider_filings(self, cik: str | int) -> list[dict[str, Any]]:
        return self.get_recent_filings(
            cik,
            forms=("4", "4/A"),
        )

    @staticmethod
    def normalize_cik(cik: str | int) -> str:
        digits = "".join(character for character in str(cik) if character.isdigit())
        if not digits:
            raise ValueError("CIK must contain digits.")
        if len(digits) > 10:
            raise ValueError("CIK cannot exceed 10 digits.")
        return digits.zfill(10)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self._client.get(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected SEC response format.")
        return payload

    @staticmethod
    def _value_at(values: list[Any], index: int) -> Any | None:
        return values[index] if index < len(values) else None
