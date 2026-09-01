from __future__ import annotations

from typing import Any

import yfinance as yf

from app.services.yahoo_fx_service import YahooFxService


class YahooMarketUniverseService:
    _SEED_UNIVERSE: tuple[dict[str, Any], ...] = (
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "country": "United States",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "regionKey": "america",
            "issuerId": "apple",
            "instrumentId": "AAPL@NASDAQ",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        {
            "symbol": "MSFT",
            "companyName": "Microsoft Corporation",
            "country": "United States",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "regionKey": "america",
            "issuerId": "microsoft",
            "instrumentId": "MSFT@NASDAQ",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Software",
        },
        {
            "symbol": "NVDA",
            "companyName": "NVIDIA Corporation",
            "country": "United States",
            "exchange": "NASDAQ",
            "exchangeShortName": "NASDAQ",
            "regionKey": "america",
            "issuerId": "nvidia",
            "instrumentId": "NVDA@NASDAQ",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Semiconductors",
        },
        {
            "symbol": "JPM",
            "companyName": "JPMorgan Chase & Co.",
            "country": "United States",
            "exchange": "NYSE",
            "exchangeShortName": "NYSE",
            "regionKey": "america",
            "issuerId": "jpmorgan-chase",
            "instrumentId": "JPM@NYSE",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Financial Services",
            "industry": "Banks",
        },
        {
            "symbol": "SAP.DE",
            "companyName": "SAP SE",
            "country": "Germany",
            "exchange": "XETRA",
            "exchangeShortName": "XETRA",
            "regionKey": "europe",
            "issuerId": "sap",
            "instrumentId": "SAP.DE@XETRA",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Software",
        },
        {
            "symbol": "SIE.DE",
            "companyName": "Siemens Aktiengesellschaft",
            "country": "Germany",
            "exchange": "XETRA",
            "exchangeShortName": "XETRA",
            "regionKey": "europe",
            "issuerId": "siemens",
            "instrumentId": "SIE.DE@XETRA",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Industrials",
            "industry": "Industrial Conglomerates",
        },
        {
            "symbol": "ASML.AS",
            "companyName": "ASML Holding N.V.",
            "country": "Netherlands",
            "exchange": "EURONEXT AMSTERDAM",
            "exchangeShortName": "EURONEXT",
            "regionKey": "europe",
            "issuerId": "asml",
            "instrumentId": "ASML.AS@EURONEXT",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Semiconductor Equipment",
        },
        {
            "symbol": "MC.PA",
            "companyName": "LVMH Moët Hennessy Louis Vuitton SE",
            "country": "France",
            "exchange": "EURONEXT PARIS",
            "exchangeShortName": "EURONEXT",
            "regionKey": "europe",
            "issuerId": "lvmh",
            "instrumentId": "MC.PA@EURONEXT",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Consumer Cyclical",
            "industry": "Luxury Goods",
        },
        {
            "symbol": "7203.T",
            "companyName": "Toyota Motor Corporation",
            "country": "Japan",
            "exchange": "TOKYO",
            "exchangeShortName": "TSE",
            "regionKey": "asia",
            "issuerId": "toyota",
            "instrumentId": "7203.T@TSE",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Consumer Cyclical",
            "industry": "Auto Manufacturers",
        },
        {
            "symbol": "6758.T",
            "companyName": "Sony Group Corporation",
            "country": "Japan",
            "exchange": "TOKYO",
            "exchangeShortName": "TSE",
            "regionKey": "asia",
            "issuerId": "sony",
            "instrumentId": "6758.T@TSE",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        {
            "symbol": "005930.KS",
            "companyName": "Samsung Electronics Co., Ltd.",
            "country": "South Korea",
            "exchange": "KOREA",
            "exchangeShortName": "KRX",
            "regionKey": "asia",
            "issuerId": "samsung-electronics",
            "instrumentId": "005930.KS@KRX",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Technology",
            "industry": "Consumer Electronics",
        },
        {
            "symbol": "9988.HK",
            "companyName": "Alibaba Group Holding Limited",
            "country": "China",
            "exchange": "HONG KONG",
            "exchangeShortName": "HKEX",
            "regionKey": "asia",
            "issuerId": "alibaba",
            "instrumentId": "9988.HK@HKEX",
            "instrumentType": "common_stock",
            "isPrimaryListing": True,
            "sector": "Consumer Cyclical",
            "industry": "Internet Retail",
        },
    )

    def __init__(
        self,
        fx_service: YahooFxService | None = None,
    ) -> None:
        self._fx_service = (
            fx_service
            if fx_service is not None
            else YahooFxService()
        )

    def get_universe(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        for configured_asset in self._SEED_UNIVERSE:
            asset = dict(configured_asset)

            market_data = self._get_market_data(
                asset["symbol"]
            )

            market_cap_local = market_data["marketCap"]
            currency = market_data["currency"]

            market_cap_usd = self._convert_market_cap_to_usd(
                market_cap_local=market_cap_local,
                currency=currency,
            )

            asset["marketCap"] = market_cap_usd
            asset["marketCapLocal"] = market_cap_local
            asset["currency"] = currency
            asset["marketCapCurrency"] = "USD"

            result.append(asset)

        return result

    def _get_market_data(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        ticker = yf.Ticker(symbol)

        try:
            fast_info = ticker.fast_info

            market_cap = self._get_fast_info_value(
                fast_info,
                "marketCap",
                "market_cap",
            )

            currency = self._get_fast_info_value(
                fast_info,
                "currency",
                "currency",
            )
        except Exception:
            return {
                "marketCap": None,
                "currency": None,
            }

        return {
            "marketCap": self._to_positive_float(
                market_cap
            ),
            "currency": self._normalize_currency(
                currency
            ),
        }

    def _convert_market_cap_to_usd(
        self,
        market_cap_local: float | None,
        currency: str | None,
    ) -> float | None:
        if market_cap_local is None:
            return None

        if currency is None:
            return None

        try:
            return self._fx_service.convert_to_usd(
                amount=market_cap_local,
                currency=currency,
            )
        except Exception:
            return None

    def _get_fast_info_value(
        self,
        fast_info: Any,
        primary_key: str,
        legacy_key: str,
    ) -> Any:
        value = fast_info.get(primary_key)

        if value is not None:
            return value

        return fast_info.get(legacy_key)

    def _normalize_currency(
        self,
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        normalized = str(value).strip().upper()

        if not normalized:
            return None

        return normalized

    def _to_positive_float(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        try:
            result = float(value)
        except (TypeError, ValueError):
            return None

        if result != result:
            return None

        if result <= 0:
            return None

        return result
