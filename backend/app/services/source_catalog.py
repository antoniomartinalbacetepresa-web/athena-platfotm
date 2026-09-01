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
    AthenaSource(
        id="yahoo_finance",
        name="Yahoo Finance",
        category="market",
        purpose=("quotes", "ohlcv_history", "indices", "etfs", "fx"),
        status="connected",
        official=False,
        free_access=True,
        requires_credentials=False,
        notes="Current primary backend market source; ATHENA must cross-check critical data where possible.",
    ),
    AthenaSource(
        id="nasdaq_trader",
        name="Nasdaq Trader",
        category="market_universe",
        purpose=("listed_symbols", "exchange_metadata", "instrument_universe"),
        status="connected",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Used to construct and validate the investable universe.",
    ),
    AthenaSource(
        id="sec_edgar_xbrl",
        name="SEC EDGAR / XBRL",
        category="fundamentals",
        purpose=("10-k", "10-q", "8-k", "20-f", "financial_statements", "filing_notes"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Primary official source for US issuer fundamentals and filings.",
    ),
    AthenaSource(
        id="sec_13f",
        name="SEC Form 13F",
        category="investors",
        purpose=("institutional_holdings", "new_positions", "increases", "reductions", "closed_positions"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Feeds ATHENA Investor Intelligence; filings are delayed and must never be treated as real-time trades.",
    ),
    AthenaSource(
        id="sec_form4",
        name="SEC Form 4",
        category="insiders",
        purpose=("insider_buys", "insider_sells", "ownership_changes"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Insider transactions require transaction-type classification before becoming a signal.",
    ),
    AthenaSource(
        id="fred_alfred",
        name="FRED / ALFRED",
        category="macro",
        purpose=("macro_series", "rates", "inflation", "employment", "historical_vintages"),
        status="credentials_required",
        official=True,
        free_access=True,
        requires_credentials=True,
        notes="FRED API key is free. ALFRED vintages are essential to reduce look-ahead/revision bias.",
    ),
    AthenaSource(
        id="ecb",
        name="European Central Bank Data Portal",
        category="macro",
        purpose=("rates", "money", "credit", "fx", "euro_area_macro"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Primary official euro-area monetary and financial source.",
    ),
    AthenaSource(
        id="finra",
        name="FINRA",
        category="positioning",
        purpose=("short_interest", "otc_transparency", "market_activity"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Short-interest data is periodic, not real-time; timestamps must be preserved.",
    ),
    AthenaSource(
        id="cftc_cot",
        name="CFTC Commitments of Traders",
        category="positioning",
        purpose=("futures_positioning", "commodities", "indices", "rates", "fx"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Useful for market positioning and macro/commodity context.",
    ),
    AthenaSource(
        id="eia",
        name="U.S. Energy Information Administration",
        category="energy",
        purpose=("oil", "gas", "inventories", "production", "electricity"),
        status="credentials_required",
        official=True,
        free_access=True,
        requires_credentials=True,
        notes="Free API key; especially relevant to energy and energy-sensitive sectors.",
    ),
    AthenaSource(
        id="world_bank",
        name="World Bank Indicators",
        category="macro",
        purpose=("country_risk", "growth", "demographics", "trade", "development"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Use a curated subset of series rather than indiscriminate ingestion.",
    ),
    AthenaSource(
        id="oecd",
        name="OECD Data Explorer",
        category="macro",
        purpose=("leading_indicators", "productivity", "employment", "trade", "confidence"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="SDMX source for international macroeconomic comparisons.",
    ),
    AthenaSource(
        id="imf",
        name="International Monetary Fund",
        category="macro",
        purpose=("balance_of_payments", "reserves", "debt", "fx", "international_macro"),
        status="ready_to_integrate",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Useful for country and cross-border macro risk.",
    ),
    AthenaSource(
        id="google_trends",
        name="Google Trends",
        category="alternative_data",
        purpose=("search_interest", "brand_interest", "emerging_topics"),
        status="restricted_access",
        official=True,
        free_access=True,
        requires_credentials=False,
        notes="Official Trends API access is limited; never make ATHENA dependent on unavailable alpha access.",
    ),
    AthenaSource(
        id="google_news",
        name="Google News / original publishers",
        category="news",
        purpose=("news_discovery", "company_events", "sector_events", "macro_events"),
        status="research_required",
        official=False,
        free_access=True,
        requires_credentials=False,
        notes="ATHENA should retain and score the original publisher, deduplicate syndicated stories, and respect terms/licensing.",
    ),
    AthenaSource(
        id="european_markets",
        name="ESMA / Euronext / national exchanges",
        category="market_universe",
        purpose=("european_instruments", "isin", "listings", "corporate_actions"),
        status="research_required",
        official=True,
        free_access=False,
        requires_credentials=False,
        notes="Use free official datasets first; some Euronext reference-data products are commercial.",
    ),
    AthenaSource(
        id="companies_house",
        name="UK Companies House",
        category="company_registry",
        purpose=("uk_company_registry", "officers", "filing_metadata"),
        status="credentials_required",
        official=True,
        free_access=True,
        requires_credentials=True,
        notes="Free developer credentials are required.",
    ),
    AthenaSource(
        id="uspto",
        name="USPTO Open Data",
        category="innovation",
        purpose=("patents", "applications", "innovation_signals"),
        status="credentials_required",
        official=True,
        free_access=True,
        requires_credentials=True,
        notes="Advanced alternative signal; lower priority than market, fundamentals and macro data.",
    ),
    AthenaSource(
        id="analyst_consensus",
        name="Analyst consensus providers",
        category="analysts",
        purpose=("ratings", "target_prices", "revisions", "upgrades", "downgrades"),
        status="research_required",
        official=False,
        free_access=False,
        requires_credentials=False,
        notes="High-value signal, but ATHENA must only integrate a provider whose licensing and cost fit the project.",
    ),
)


def get_source_catalog() -> list[dict[str, object]]:
    return [source.to_dict() for source in SOURCES]


def get_source_summary() -> dict[str, int]:
    summary: dict[str, int] = {}
    for source in SOURCES:
        summary[source.status] = summary.get(source.status, 0) + 1
    summary["total"] = len(SOURCES)
    return summary
