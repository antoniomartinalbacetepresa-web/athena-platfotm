from __future__ import annotations

import csv
from io import StringIO
from typing import Any

import httpx


class NasdaqTraderUniverseSource:
    source_id = "nasdaq_trader"

    _NASDAQ_LISTED_URL = (
        "https://www.nasdaqtrader.com/"
        "dynamic/SymDir/nasdaqlisted.txt"
    )

    _OTHER_LISTED_URL = (
        "https://www.nasdaqtrader.com/"
        "dynamic/SymDir/otherlisted.txt"
    )

    _OTHER_EXCHANGE_NAMES = {
        "A": "NYSE AMERICAN",
        "N": "NYSE",
        "P": "NYSE ARCA",
        "Z": "CBOE BZX",
        "V": "IEX",
    }

    _OTHER_EXCHANGE_SHORT_NAMES = {
        "A": "NYSEAMERICAN",
        "N": "NYSE",
        "P": "NYSEARCA",
        "Z": "BZX",
        "V": "IEX",
    }

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._owns_client = client is None

        self._client = (
            client
            if client is not None
            else httpx.Client(
                timeout=timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "ATHENA-TYCHE/0.1 "
                        "market-universe-importer"
                    ),
                },
            )
        )

    def get_instruments(
        self,
    ) -> list[dict[str, Any]]:
        nasdaq_text = self._download(
            self._NASDAQ_LISTED_URL
        )

        other_text = self._download(
            self._OTHER_LISTED_URL
        )

        return [
            *self._parse_nasdaq_listed(
                nasdaq_text
            ),
            *self._parse_other_listed(
                other_text
            ),
        ]

    def dispose(self) -> None:
        if self._owns_client:
            self._client.close()

    def _download(
        self,
        url: str,
    ) -> str:
        response = self._client.get(
            url
        )

        response.raise_for_status()

        text = response.text

        if not text.strip():
            raise RuntimeError(
                "Nasdaq Trader devolvió "
                "un fichero vacío."
            )

        return text

    def _parse_nasdaq_listed(
        self,
        text: str,
    ) -> list[dict[str, Any]]:
        rows = self._read_pipe_rows(
            text
        )

        result: list[
            dict[str, Any]
        ] = []

        for row in rows:
            symbol = self._clean_text(
                row.get("Symbol")
            )

            security_name = self._clean_text(
                row.get("Security Name")
            )

            test_issue = self._clean_text(
                row.get("Test Issue")
            )

            if (
                symbol is None
                or security_name is None
                or test_issue == "Y"
            ):
                continue

            result.append(
                {
                    "symbol": symbol,
                    "companyName": security_name,
                    "exchange": "NASDAQ",
                    "exchangeShortName": "NASDAQ",
                    "instrumentType": (
                        self._infer_instrument_type(
                            security_name=security_name,
                            etf_flag=row.get(
                                "ETF"
                            ),
                        )
                    ),
                    "isPrimaryListing": False,
                    "sourceProvider": self.source_id,
                    "isActive": True,
                }
            )

        return result

    def _parse_other_listed(
        self,
        text: str,
    ) -> list[dict[str, Any]]:
        rows = self._read_pipe_rows(
            text
        )

        result: list[
            dict[str, Any]
        ] = []

        for row in rows:
            symbol = (
                self._clean_text(
                    row.get("ACT Symbol")
                )
                or self._clean_text(
                    row.get("NASDAQ Symbol")
                )
            )

            security_name = self._clean_text(
                row.get("Security Name")
            )

            exchange_code = self._clean_text(
                row.get("Exchange")
            )

            test_issue = self._clean_text(
                row.get("Test Issue")
            )

            if (
                symbol is None
                or security_name is None
                or exchange_code is None
                or test_issue == "Y"
            ):
                continue

            exchange = (
                self._OTHER_EXCHANGE_NAMES.get(
                    exchange_code,
                    exchange_code,
                )
            )

            exchange_short_name = (
                self._OTHER_EXCHANGE_SHORT_NAMES.get(
                    exchange_code,
                    exchange_code,
                )
            )

            result.append(
                {
                    "symbol": symbol,
                    "companyName": security_name,
                    "exchange": exchange,
                    "exchangeShortName": (
                        exchange_short_name
                    ),
                    "instrumentType": (
                        self._infer_instrument_type(
                            security_name=security_name,
                            etf_flag=row.get(
                                "ETF"
                            ),
                        )
                    ),
                    "isPrimaryListing": False,
                    "sourceProvider": self.source_id,
                    "isActive": True,
                }
            )

        return result

    def _read_pipe_rows(
        self,
        text: str,
    ) -> list[dict[str, str]]:
        normalized_lines: list[str] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith(
                "File Creation Time:"
            ):
                continue

            normalized_lines.append(
                line
            )

        if not normalized_lines:
            return []

        reader = csv.DictReader(
            StringIO(
                "\n".join(
                    normalized_lines
                )
            ),
            delimiter="|",
        )

        return [
            dict(row)
            for row in reader
        ]

    def _infer_instrument_type(
        self,
        security_name: str,
        etf_flag: Any,
    ) -> str:
        normalized_name = (
            " "
            + " ".join(
                security_name.upper().split()
            )
            + " "
        )

        normalized_etf_flag = (
            self._clean_text(
                etf_flag
            )
        )

        if normalized_etf_flag == "Y":
            return "etf"

        if self._contains_any(
            normalized_name,
            (
                " WARRANT ",
                " WARRANTS ",
                " WARRANT. ",
                " WARRANTS. ",
            ),
        ):
            return "warrant"

        if self._contains_any(
            normalized_name,
            (
                " RIGHTS ",
                " RIGHT ",
                " RIGHTS. ",
                " RIGHT. ",
            ),
        ):
            return "right"

        if self._contains_any(
            normalized_name,
            (
                " - UNITS ",
                " - UNIT ",
                " UNITS ",
                " UNIT. ",
                " UNITS. ",
                " TANGIBLE EQUITY UNIT ",
                " COMMON UNITS ",
            ),
        ):
            return "unit"

        if self._contains_any(
            normalized_name,
            (
                " PREFERRED ",
                " PREFERENCE SHARES ",
                " PREFERENCE SHARE ",
                " PFD ",
                " PREF ",
            ),
        ):
            return "preferred_stock"

        if self._contains_any(
            normalized_name,
            (
                " ADR ",
                " ADRS ",
                " ADS ",
                " ADSS ",
                " AMERICAN DEPOSITARY ",
                " AMERICAN DEPOSITORY ",
                " GLOBAL DEPOSITARY ",
            ),
        ):
            return "adr"

        if self._contains_any(
            normalized_name,
            (
                " DEPOSITARY SHARES ",
                " DEPOSITARY SHARE ",
                " NEW YORK REGISTRY SHARE ",
                " NEW YORK REGISTRY SHARES ",
                " NY REGISTRY SHARE ",
                " NY REGISTRY SHARES ",
            ),
        ):
            return "depositary_receipt"

        if self._contains_any(
            normalized_name,
            (
                " ETN ",
                " ETNS ",
                " EXCHANGE-TRADED NOTES",
                " EXCHANGE TRADED NOTE",
                " EXCHANGE TRADED NOTES",
                " SENIOR NOTE",
                " SENIOR NOTES",
                " SUBORDINATED NOTE",
                " SUBORDINATED NOTES",
                " JUNIOR SUBORDINATED NOTE",
                " JUNIOR SUBORDINATED NOTES",
                " NOTE DUE",
                " NOTES DUE",
                " FIRST MORTGAGE BOND",
                " FIRST MORTGAGE BONDS",
                " BOND ",
                " BONDS ",
                " DEBENTURE ",
                " DEBENTURES ",
            ),
        ):
            return "debt"

        if self._contains_any(
            normalized_name,
            (
                " BUSINESS DEVELOPMENT COMPANY ",
                " CLOSED-END FUND ",
                " CLOSED END FUND ",
                " INVESTMENT FUND ",
                " HIGH YIELD FUND ",
                " INCOME FUND ",
                " MUNIYIELD ",
            ),
        ):
            return "fund"

        if self._contains_any(
            normalized_name,
            (
                " COMMON STOCK ",
                " COMMON STOCK, ",
                " COMMON STOCK REIT ",
                " COMMON SHARE ",
                " COMMON SHARES ",
                " COMMON SHARES, ",
                " CLASS A COMMON ",
                " COMMON NEW ",
                " ORDINARY SHARE ",
                " ORDINARY SHARES ",
                " ORDINARY SHARES, ",
                " ORD SHARE ",
                " ORD SHARES ",
                " SUBORDINATE VOTING SHARE ",
                " SUBORDINATE VOTING SHARES ",
                " LIMITED VOTING SHARE ",
                " LIMITED VOTING SHARES ",
                " REGISTERED SHARE ",
                " REGISTERED SHARES ",
                " CAPITAL STOCK ",
                " CLASS A SHARES ",
            ),
        ):
            return "common_stock"

        if self._contains_any(
            normalized_name,
            (
                " FUND ",
                " TRUST ",
            ),
        ):
            return "fund"

        return "unknown"

    def _contains_any(
        self,
        normalized_name: str,
        patterns: tuple[str, ...],
    ) -> bool:
        return any(
            pattern in normalized_name
            for pattern in patterns
        )

    def _clean_text(
        self,
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized
