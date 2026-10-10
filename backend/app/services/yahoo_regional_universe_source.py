from __future__ import annotations

from typing import Any, Callable

import yfinance as yf

from app.services.yahoo_fx_service import YahooFxService


ProgressCallback = Callable[[dict[str, Any]], None]


class YahooRegionalUniverseSource:
    """Discovers sizeable listed equities by Yahoo region without manual seeds."""

    source_id = "yahoo_regional_screener"
    EXHAUSTIVE_SAFETY_MAX_PAGES = 200
    EXHAUSTIVE_MAX_CONSECUTIVE_NO_NEW_SYMBOL_PAGES = 2

    DEFAULT_REGIONS = (
        # United States is included here because the weighted universe needs
        # market capitalization; Nasdaq Trader remains a catalog/identity
        # source and does not provide market cap by itself.
        "us",
        # Europe
        "gb", "de", "fr", "ch", "nl", "se", "it", "es", "dk", "no",
        "fi", "be", "at", "ie", "pt", "pl",
        # Asia
        "jp", "cn", "hk", "kr", "in", "tw", "sg", "id", "my", "th",
        "ph", "vn",
        # Americas outside the US
        "ca", "mx", "br", "ar", "cl", "co", "pe",
    )

    _COUNTRIES = {
        "ar": "Argentina",
        "at": "Austria",
        "be": "Belgium",
        "br": "Brazil",
        "ca": "Canada",
        "ch": "Switzerland",
        "cl": "Chile",
        "cn": "China",
        "co": "Colombia",
        "de": "Germany",
        "dk": "Denmark",
        "es": "Spain",
        "fi": "Finland",
        "fr": "France",
        "gb": "United Kingdom",
        "hk": "Hong Kong",
        "id": "Indonesia",
        "ie": "Ireland",
        "in": "India",
        "it": "Italy",
        "jp": "Japan",
        "kr": "South Korea",
        "mx": "Mexico",
        "my": "Malaysia",
        "nl": "Netherlands",
        "no": "Norway",
        "pe": "Peru",
        "ph": "Philippines",
        "pl": "Poland",
        "pt": "Portugal",
        "se": "Sweden",
        "sg": "Singapore",
        "th": "Thailand",
        "tw": "Taiwan",
        "us": "United States",
        "vn": "Vietnam",
    }

    _ATHENA_REGION = {
        **{
            code: "america"
            for code in ("ar", "br", "ca", "cl", "co", "mx", "pe", "us")
        },
        **{
            code: "europe"
            for code in (
                "at", "be", "ch", "de", "dk", "es", "fi", "fr", "gb",
                "ie", "it", "nl", "no", "pl", "pt", "se",
            )
        },
        **{
            code: "asia"
            for code in (
                "cn", "hk", "id", "in", "jp", "kr", "my", "ph", "sg",
                "th", "tw", "vn",
            )
        },
    }

    def __init__(
        self,
        *,
        regions: tuple[str, ...] | None = None,
        page_size: int = 250,
        max_pages_per_region: int | None = 1,
        screen_function: Callable[..., dict[str, Any]] | None = None,
        query_factory: Callable[..., Any] | None = None,
        fx_service: YahooFxService | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if page_size <= 0 or page_size > 250:
            raise ValueError("page_size debe estar entre 1 y 250.")
        if max_pages_per_region is not None and max_pages_per_region <= 0:
            raise ValueError("max_pages_per_region debe ser mayor que 0 o None.")

        self._regions = regions or self.DEFAULT_REGIONS
        self._page_size = page_size
        self._max_pages = max_pages_per_region
        self._screen = screen_function if screen_function is not None else yf.screen
        self._query_factory = (
            query_factory if query_factory is not None else yf.EquityQuery
        )
        self._fx_service = fx_service if fx_service is not None else YahooFxService()
        self._progress_callback = progress_callback

    def get_instruments(self) -> list[dict[str, Any]]:
        assets: dict[str, dict[str, Any]] = {}

        for region_code in self._regions:
            normalized_region = str(region_code).strip().lower()
            if normalized_region not in self._COUNTRIES:
                raise ValueError(f"Región Yahoo no soportada: {region_code}")

            page = 0
            previous_page_signature: tuple[str, ...] | None = None
            consecutive_no_new_symbol_pages = 0

            while self._max_pages is None or page < self._max_pages:
                if (
                    self._max_pages is None
                    and page >= self.EXHAUSTIVE_SAFETY_MAX_PAGES
                ):
                    self._emit_progress(
                        region=normalized_region,
                        page=page,
                        received=0,
                        total=None,
                        accumulated=len(assets),
                        status="safety_limit",
                        new_symbols=0,
                    )
                    break

                offset = page * self._page_size
                response = self._screen_region(normalized_region, offset)
                quotes = response.get("quotes")
                total = self._integer(response.get("total"))

                if not isinstance(quotes, list) or not quotes:
                    self._emit_progress(
                        region=normalized_region,
                        page=page,
                        received=0,
                        total=total,
                        accumulated=len(assets),
                        status="completed",
                        new_symbols=0,
                    )
                    break

                page_signature = tuple(
                    str(quote.get("symbol") or "").strip().upper()
                    for quote in quotes
                    if isinstance(quote, dict)
                )

                if (
                    previous_page_signature is not None
                    and page_signature == previous_page_signature
                ):
                    self._emit_progress(
                        region=normalized_region,
                        page=page,
                        received=len(quotes),
                        total=total,
                        accumulated=len(assets),
                        status="repeated_page",
                        new_symbols=0,
                    )
                    break

                previous_page_signature = page_signature
                assets_before_page = len(assets)

                for quote in quotes:
                    if not isinstance(quote, dict):
                        continue
                    asset = self._map_quote(normalized_region, quote)
                    if asset is None:
                        continue
                    key = (
                        f"{asset['symbol']}@"
                        f"{asset.get('exchangeShortName') or ''}"
                    )
                    assets[key] = asset

                new_symbols = len(assets) - assets_before_page
                if new_symbols == 0:
                    consecutive_no_new_symbol_pages += 1
                else:
                    consecutive_no_new_symbol_pages = 0

                status = "page_completed"
                if (
                    self._max_pages is None
                    and consecutive_no_new_symbol_pages
                    >= self.EXHAUSTIVE_MAX_CONSECUTIVE_NO_NEW_SYMBOL_PAGES
                ):
                    status = "no_new_symbols"

                self._emit_progress(
                    region=normalized_region,
                    page=page,
                    received=len(quotes),
                    total=total,
                    accumulated=len(assets),
                    status=status,
                    new_symbols=new_symbols,
                )

                if status == "no_new_symbols":
                    break
                if total is not None and offset + len(quotes) >= total:
                    break
                if len(quotes) < self._page_size:
                    break

                page += 1

        return list(assets.values())

    def _emit_progress(
        self,
        *,
        region: str,
        page: int,
        received: int,
        total: int | None,
        accumulated: int,
        status: str,
        new_symbols: int,
    ) -> None:
        if self._progress_callback is None:
            return

        self._progress_callback(
            {
                "region": region,
                "country": self._COUNTRIES[region],
                "page": page + 1,
                "received": received,
                "total": total,
                "accumulated": accumulated,
                "newSymbols": new_symbols,
                "status": status,
            }
        )

    def _screen_region(self, region_code: str, offset: int) -> dict[str, Any]:
        query = self._query_factory(
            "and",
            [
                self._query_factory("eq", ["region", region_code]),
                self._query_factory("gt", ["intradaymarketcap", 0]),
            ],
        )
        response = self._screen(
            query,
            offset=offset,
            size=self._page_size,
            sortField="intradaymarketcap",
            sortAsc=False,
        )
        if not isinstance(response, dict):
            raise RuntimeError(
                f"Yahoo no devolvió un screener válido para {region_code}."
            )
        return response

    def _map_quote(
        self,
        region_code: str,
        quote: dict[str, Any],
    ) -> dict[str, Any] | None:
        symbol = self._text(quote.get("symbol"))
        if symbol is None:
            return None

        quote_type = self._upper_text(quote.get("quoteType"))
        if quote_type is not None and quote_type != "EQUITY":
            return None

        company_name = self._text(
            quote.get("longName") or quote.get("shortName") or symbol
        )
        exchange = self._upper_text(
            quote.get("exchange") or quote.get("fullExchangeName")
        )
        currency = self._upper_text(quote.get("currency"))
        market_cap_local = self._positive_float(
            quote.get("marketCap")
            or quote.get("intradaymarketcap")
            or quote.get("lastclosemarketcap.lasttwelvemonths")
        )

        market_cap_usd: float | None = None
        if market_cap_local is not None and currency is not None:
            try:
                market_cap_usd = self._fx_service.convert_to_usd(
                    amount=market_cap_local,
                    currency=currency,
                )
            except Exception:
                pass

        return {
            "symbol": symbol.upper(),
            "companyName": company_name,
            "country": self._COUNTRIES[region_code],
            "regionKey": self._ATHENA_REGION[region_code],
            "exchange": exchange,
            "exchangeShortName": exchange,
            "instrumentType": "common_stock",
            "isPrimaryListing": False,
            "sector": self._text(quote.get("sector")),
            "industry": self._text(quote.get("industry")),
            "currency": currency,
            "marketCap": market_cap_usd,
            "marketCapLocal": market_cap_local,
            "marketCapCurrency": currency,
            "sourceProvider": self.source_id,
            "isActive": True,
        }

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _upper_text(self, value: Any) -> str | None:
        normalized = self._text(value)
        return normalized.upper() if normalized is not None else None

    def _positive_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result or result <= 0:
            return None
        return result

    def _integer(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
