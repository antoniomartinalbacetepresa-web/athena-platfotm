from __future__ import annotations

from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.services.yahoo_market_universe_service import YahooMarketUniverseService


class MarketUniverseFallback(Protocol):
    def get_universe(self) -> list[dict[str, Any]]:
        ...


class PersistedMarketUniverseService:
    """Sirve el universo activo persistido con fallback seguro al seed."""

    def __init__(
        self,
        database: AthenaDatabase | None = None,
        fallback_service: MarketUniverseFallback | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)
        self._fallback_service = (
            fallback_service
            if fallback_service is not None
            else YahooMarketUniverseService()
        )

    def get_universe(self) -> list[dict[str, Any]]:
        self._database.initialize()
        rows = self._repository.list_active()

        if not rows:
            return self._fallback_service.get_universe()

        return [self._to_api_asset(row) for row in rows]

    def _to_api_asset(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": row["symbol"],
            "companyName": row["company_name"],
            "marketCap": row["market_cap_usd"],
            "marketCapLocal": row["market_cap_local"],
            "marketCapCurrency": row["market_cap_local_currency"],
            "country": row["country"],
            "exchange": row["exchange"],
            "exchangeShortName": row["exchange_short_name"],
            "regionKey": row["region_key"],
            "issuerId": row["issuer_id"],
            "instrumentId": row["instrument_id"],
            "instrumentType": row["instrument_type"],
            "isPrimaryListing": bool(row["is_primary_listing"]),
            "sector": row["sector"],
            "industry": row["industry"],
            "currency": row["currency"],
            "sourceProvider": row["source_provider"],
            "sourceTimestamp": row["source_timestamp"],
            "retrievedAt": row["retrieved_at"],
        }
