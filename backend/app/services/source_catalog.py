from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


SourceStatus = Literal[
    "connected",
    "ready_to_integrate",
    "credentials_required",
    "restricted_access",
    "research_required",
]


@dataclass(frozen=True)
class AthenaSource:
    id: str
    name: str
    category: str
    purpose: tuple[str, ...]
    status: SourceStatus
    official: bool
    free_access: bool
    requires_credentials: bool
    notes: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["purpose"] = list(self.purpose)
        return data


SOURCES: tuple[AthenaSource, ...] = (
    AthenaSource("yahoo_finance", "Yahoo Finance", "market", ("quotes", "ohlcv_history", "indices", "etfs", "fx"), "connected", False, True, False, "Current primary backend market source; cross-check critical data where possible."),
    AthenaSource("nasdaq_trader", "Nasdaq Trader", "market_universe", ("listed_symbols", "exchange_metadata", "instrument_universe"), "connected", True, True, False, "Used to construct and validate the investable universe."),
    AthenaSource("sec_edgar_xbrl", "SEC EDGAR / XBRL", "fundamentals", ("10-k", "10-q", "8-k", "20-f", "financial_statements", "filing_notes"), "connected", True, True, False, "Official US issuer fundamentals and filings through the ATHENA backend SEC connector."),
    AthenaSource("sec_13f", "SEC Form 13F", "investors", ("institutional_holdings", "new_positions", "increases", "reductions", "closed_positions"), "connected", True, True, False, "ATHENA backend can retrieve 13F filings; holdings are delayed and must never be treated as real-time trades."),
    AthenaSource("sec_form4", "SEC Form 4", "insiders", ("insider_buys", "insider_sells", "ownership_changes"), "connected", True, True, False, "ATHENA backend can retrieve Form 4 filings; transactions still require semantic classification before becoming a signal."),
    AthenaSource("fred_alfred", "FRED / ALFRED", "macro", ("macro_series", "rates", "inflation", "employment", "historical_vintages"), "credentials_required", True, True, True, "FRED requires an API key. ALFRED vintage dates are essential to reduce look-ahead and revision bias."),
    AthenaSource("ecb", "European Central Bank Data Portal", "macro", ("rates", "money", "credit", "fx", "euro_area_macro"), "connected", True, True, False, "ATHENA backend has an ECB SDMX connector for euro-area monetary and financial series."),
    AthenaSource("bls", "U.S. Bureau of Labor Statistics", "macro", ("employment", "cpi", "wages", "productivity", "labor_costs"), "ready_to_integrate", True, True, False, "Use directly when BLS adds detail not adequately covered by FRED."),
    AthenaSource("bea", "U.S. Bureau of Economic Analysis", "macro", ("gdp", "income", "consumption", "corporate_profits", "industry_accounts"), "credentials_required", True, True, True, "Free API key; use for official US national and industry accounts."),
    AthenaSource("finra", "FINRA", "positioning", ("short_interest", "otc_transparency", "market_activity"), "ready_to_integrate", True, True, False, "Short-interest data is periodic, not real-time; preserve report timestamps."),
    AthenaSource("cftc_cot", "CFTC Commitments of Traders", "positioning", ("futures_positioning", "commodities", "indices", "rates", "fx"), "ready_to_integrate", True, True, False, "Official public reporting API supports COT filtering and historical analysis."),
    AthenaSource("eia", "U.S. Energy Information Administration", "energy", ("oil", "gas", "inventories", "production", "electricity"), "credentials_required", True, True, True, "Free API key; relevant to energy and energy-sensitive sectors."),
    AthenaSource("world_bank", "World Bank Indicators", "macro", ("country_risk", "growth", "demographics", "trade", "development"), "connected", True, True, False, "ATHENA backend has a World Bank connector; ingest a curated subset of useful series."),
    AthenaSource("oecd", "OECD Data Explorer", "macro", ("leading_indicators", "productivity", "employment", "trade", "confidence"), "ready_to_integrate", True, True, False, "SDMX source for international macro comparisons."),
    AthenaSource("imf", "International Monetary Fund", "macro", ("balance_of_payments", "reserves", "debt", "fx", "international_macro"), "ready_to_integrate", True, True, False, "Useful for country and cross-border macro risk."),
    AthenaSource("google_trends", "Google Trends", "alternative_data", ("search_interest", "brand_interest", "emerging_topics"), "restricted_access", True, True, False, "Official API access is limited; ATHENA must not depend on unavailable access."),
    AthenaSource("google_news", "Google News / original publishers", "news", ("news_discovery", "company_events", "sector_events", "macro_events"), "research_required", False, True, False, "Retain original publisher, deduplicate syndication, and respect licensing and terms."),
    AthenaSource("google_finance", "Google Finance", "verification", ("quote_cross_check", "market_context"), "research_required", False, True, False, "Complementary verification only; not a primary programmatic market-data dependency."),
    AthenaSource("tradingview", "TradingView", "research_platform", ("chart_cross_check", "technical_context", "market_visualization"), "research_required", False, False, False, "Use only through an authorized integration or as human-verification context; never rely on unauthorized scraping."),
    AthenaSource("finviz", "Finviz", "research_platform", ("screening", "fundamentals_cross_check", "insiders_cross_check", "short_interest_cross_check", "market_maps"), "research_required", False, False, False, "Useful research cross-check; programmatic ingestion depends on permitted access and licensing."),
    AthenaSource("tikr", "TIKR", "research_platform", ("financials_cross_check", "estimates", "comparables", "valuation_cross_check"), "research_required", False, False, False, "High-value comparison source; do not automate ingestion without suitable access and redistribution rights."),
    AthenaSource("koyfin", "Koyfin", "research_platform", ("market_cross_check", "macro_cross_check", "valuation_cross_check", "estimates"), "research_required", False, False, False, "Research and verification platform unless an authorized programmatic integration is available."),
    AthenaSource("justetf", "justETF", "fund_research", ("etf_characteristics", "costs", "exposures", "holdings_cross_check", "fund_comparison"), "research_required", False, False, False, "Useful for European ETF research; integration must respect platform terms and data licensing."),
    AthenaSource("stock_analysis", "Stock Analysis", "research_platform", ("financials_cross_check", "ratios", "estimates", "dividends", "valuation_cross_check"), "research_required", False, True, False, "Complementary verification source; primary fundamentals should prefer issuer filings and official data."),
    AthenaSource("european_markets", "ESMA / Euronext / national exchanges", "market_universe", ("european_instruments", "isin", "listings", "corporate_actions"), "research_required", True, False, False, "Prefer free official datasets; some reference-data products are commercial."),
    AthenaSource("companies_house", "UK Companies House", "company_registry", ("uk_company_registry", "officers", "filing_metadata"), "credentials_required", True, True, True, "Free developer credentials are required."),
    AthenaSource("uspto", "USPTO Open Data", "innovation", ("patents", "applications", "innovation_signals"), "credentials_required", True, True, True, "Advanced alternative signal; lower priority than market, fundamentals and macro."),
    AthenaSource("analyst_consensus", "Analyst consensus providers", "analysts", ("ratings", "target_prices", "revisions", "upgrades", "downgrades"), "research_required", False, False, False, "Integrate only providers whose licensing, redistribution rights and cost fit ATHENA."),
)


def get_source_catalog() -> list[dict[str, object]]:
    return [source.to_dict() for source in SOURCES]


def get_source_summary() -> dict[str, int]:
    summary: dict[str, int] = {}
    for source in SOURCES:
        summary[source.status] = summary.get(source.status, 0) + 1
    summary["total"] = len(SOURCES)
    return summary
