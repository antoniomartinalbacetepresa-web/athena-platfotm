from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.sec_edgar_service import SecEdgarService


class SecTickerAssociationProvider(Protocol):
    def get_company_ticker_exchange_associations(self) -> list[dict[str, str]]:
        ...


@dataclass(frozen=True)
class SecIssuerResolutionPreviewReport:
    eligible_us_listing_count: int
    matched_listing_count: int
    ambiguous_listing_count: int
    unmatched_listing_count: int
    matched_unique_cik_count: int
    eligible_market_cap_usd: float
    matched_market_cap_usd: float
    top_unmatched_listings: tuple[dict[str, Any], ...]
    top_ambiguous_listings: tuple[dict[str, Any], ...]

    @property
    def listing_coverage(self) -> float:
        if self.eligible_us_listing_count <= 0:
            return 0.0
        return self.matched_listing_count / self.eligible_us_listing_count

    @property
    def market_cap_coverage(self) -> float:
        if self.eligible_market_cap_usd <= 0:
            return 0.0
        return self.matched_market_cap_usd / self.eligible_market_cap_usd

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "source": "sec_company_tickers_exchange",
            "scope": "us_listings_with_positive_market_cap",
            "warning": (
                "La SEC indica que las asociaciones ticker/CIK/exchange se "
                "actualizan periódicamente pero no garantizan exactitud ni cobertura "
                "total. Este informe no modifica la base local."
            ),
            "eligibleUsListingCount": self.eligible_us_listing_count,
            "matchedListingCount": self.matched_listing_count,
            "ambiguousListingCount": self.ambiguous_listing_count,
            "unmatchedListingCount": self.unmatched_listing_count,
            "listingCoverage": self.listing_coverage,
            "matchedUniqueCikCount": self.matched_unique_cik_count,
            "eligibleMarketCapUsd": self.eligible_market_cap_usd,
            "matchedMarketCapUsd": self.matched_market_cap_usd,
            "marketCapCoverage": self.market_cap_coverage,
            "topUnmatchedListings": [
                dict(item) for item in self.top_unmatched_listings
            ],
            "topAmbiguousListings": [
                dict(item) for item in self.top_ambiguous_listings
            ],
        }


class SecIssuerResolutionPreviewService:
    """Measures SEC CIK coverage for persisted US listings without mutation."""

    _TOP_DIAGNOSTIC_LISTINGS = 50

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        sec_provider: SecTickerAssociationProvider | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)
        self._sec_provider = (
            sec_provider if sec_provider is not None else SecEdgarService()
        )

    def get_report(self) -> SecIssuerResolutionPreviewReport:
        self._database.initialize()
        eligible = [
            row
            for row in self._repository.list_active()
            if self._is_eligible_us_listing(row)
        ]
        associations = self._sec_provider.get_company_ticker_exchange_associations()

        by_ticker: dict[str, dict[str, dict[str, str]]] = {}
        for association in associations:
            ticker = str(association.get("ticker") or "").strip().upper()
            cik = str(association.get("cik") or "").strip()
            if not ticker or not cik:
                continue
            by_ticker.setdefault(ticker, {})[cik] = association

        matched_count = 0
        ambiguous_count = 0
        matched_ciks: set[str] = set()
        eligible_market_cap = 0.0
        matched_market_cap = 0.0
        unmatched: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []

        for row in eligible:
            symbol = str(row.get("symbol") or "").strip().upper()
            cap = float(row["market_cap_usd"])
            eligible_market_cap += cap
            candidates = list(by_ticker.get(symbol, {}).values())

            if len(candidates) == 1:
                matched_count += 1
                matched_market_cap += cap
                matched_ciks.add(str(candidates[0]["cik"]))
                continue

            diagnostic = {
                "symbol": symbol,
                "companyName": str(row.get("company_name") or ""),
                "exchange": str(
                    row.get("exchange_short_name")
                    or row.get("exchange")
                    or ""
                ),
                "marketCapUsd": cap,
            }
            if not candidates:
                unmatched.append(diagnostic)
                continue

            ambiguous_count += 1
            ambiguous.append(
                {
                    **diagnostic,
                    "candidateCiks": sorted(
                        {str(candidate["cik"]) for candidate in candidates}
                    ),
                    "candidateNames": sorted(
                        {str(candidate["name"]) for candidate in candidates}
                    ),
                }
            )

        unmatched.sort(key=lambda item: float(item["marketCapUsd"]), reverse=True)
        ambiguous.sort(key=lambda item: float(item["marketCapUsd"]), reverse=True)

        return SecIssuerResolutionPreviewReport(
            eligible_us_listing_count=len(eligible),
            matched_listing_count=matched_count,
            ambiguous_listing_count=ambiguous_count,
            unmatched_listing_count=len(unmatched),
            matched_unique_cik_count=len(matched_ciks),
            eligible_market_cap_usd=eligible_market_cap,
            matched_market_cap_usd=matched_market_cap,
            top_unmatched_listings=tuple(
                unmatched[: self._TOP_DIAGNOSTIC_LISTINGS]
            ),
            top_ambiguous_listings=tuple(
                ambiguous[: self._TOP_DIAGNOSTIC_LISTINGS]
            ),
        )

    def _is_eligible_us_listing(self, row: dict[str, Any]) -> bool:
        cap = row.get("market_cap_usd")
        if not isinstance(cap, (int, float)) or cap <= 0:
            return False
        country = str(row.get("country") or "").strip().casefold()
        symbol = str(row.get("symbol") or "").strip()
        return country in {"united states", "united states of america"} and bool(symbol)
