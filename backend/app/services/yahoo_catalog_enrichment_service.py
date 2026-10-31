from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.instrument_repository import InstrumentRepository
from app.services.global_universe_import_service import UniverseImportReport
from app.services.market_region_classifier import MarketRegionClassifier
from app.services.source_aware_universe_import_service import (
    SourceAwareUniverseImportService,
)
from app.services.yahoo_fx_service import YahooFxService
from app.services.yahoo_instrument_metadata_service import (
    YahooInstrumentMetadataService,
)


class InstrumentMetadataProvider(Protocol):
    source_id: str

    def get_metadata(self, symbol: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class YahooCatalogEnrichmentReport:
    candidates: int
    attempted: int
    enriched: int
    failed: int
    failures: tuple[dict[str, str], ...]
    import_report: UniverseImportReport | None


@dataclass(frozen=True)
class _EnrichmentSource:
    source_id: str
    instruments: tuple[dict[str, Any], ...]

    def get_instruments(self):
        return iter(self.instruments)


class YahooCatalogEnrichmentService:
    """Enriches persisted listings in bounded batches without fabricating data."""

    def __init__(
        self,
        *,
        instrument_repository: InstrumentRepository,
        import_service: SourceAwareUniverseImportService,
        metadata_service: InstrumentMetadataProvider | None = None,
        fx_service: YahooFxService | None = None,
        region_classifier: MarketRegionClassifier | None = None,
    ) -> None:
        self._instrument_repository = instrument_repository
        self._import_service = import_service
        self._metadata_service = (
            metadata_service
            if metadata_service is not None
            else YahooInstrumentMetadataService()
        )
        self._fx_service = fx_service if fx_service is not None else YahooFxService()
        self._region_classifier = (
            region_classifier
            if region_classifier is not None
            else MarketRegionClassifier()
        )

    def enrich(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        incomplete_only: bool = True,
    ) -> YahooCatalogEnrichmentReport:
        if limit <= 0:
            raise ValueError("limit debe ser mayor que 0.")
        if offset < 0:
            raise ValueError("offset no puede ser negativo.")

        rows = self._instrument_repository.list_active(
            limit=limit,
            offset=offset,
        )
        candidates = [
            row
            for row in rows
            if not incomplete_only or self._needs_enrichment(row)
        ]

        enriched_records: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        for row in candidates:
            symbol = str(row["symbol"])
            try:
                metadata = self._metadata_service.get_metadata(symbol)
                enriched_records.append(self._merge(row, metadata))
            except Exception as exc:
                failures.append(
                    {
                        "symbol": symbol,
                        "error": str(exc) or exc.__class__.__name__,
                    }
                )

        import_report: UniverseImportReport | None = None
        if enriched_records:
            import_report = self._import_service.import_source(
                _EnrichmentSource(
                    source_id=self._metadata_service.source_id,
                    instruments=tuple(enriched_records),
                )
            )

        return YahooCatalogEnrichmentReport(
            candidates=len(candidates),
            attempted=len(candidates),
            enriched=len(enriched_records),
            failed=len(failures),
            failures=tuple(failures),
            import_report=import_report,
        )

    def _needs_enrichment(self, row: dict[str, Any]) -> bool:
        return any(
            (
                not str(row.get("country") or "").strip(),
                not str(row.get("region_key") or "").strip(),
                not self._positive_number(row.get("market_cap_usd")),
                not str(row.get("sector") or "").strip(),
            )
        )

    def _merge(
        self,
        row: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        country = self._first_text(metadata.get("country"), row.get("country"))
        region_key = self._region_classifier.classify(country) or self._first_text(
            row.get("region_key")
        )
        currency = self._first_text(metadata.get("currency"), row.get("currency"))
        market_cap_local = self._positive_value(
            metadata.get("marketCapLocal")
        ) or self._positive_value(row.get("market_cap_local"))

        market_cap_usd = self._positive_value(row.get("market_cap_usd"))
        if market_cap_local is not None and currency is not None:
            try:
                market_cap_usd = self._fx_service.convert_to_usd(
                    amount=market_cap_local,
                    currency=currency,
                )
            except Exception:
                # Unsupported/unavailable FX is not converted by approximation.
                pass

        instrument_type = self._first_text(
            metadata.get("instrumentType"),
            row.get("instrument_type"),
        ) or "unknown"
        if instrument_type == "unknown":
            instrument_type = self._first_text(row.get("instrument_type")) or "unknown"

        return {
            "symbol": row["symbol"],
            "companyName": self._first_text(
                metadata.get("companyName"),
                row.get("company_name"),
            ),
            "issuerId": row.get("issuer_id"),
            "instrumentId": row.get("instrument_id"),
            "country": country,
            "regionKey": region_key,
            "exchange": self._first_text(
                metadata.get("exchange"),
                row.get("exchange"),
            ),
            "exchangeShortName": row.get("exchange_short_name"),
            "instrumentType": instrument_type,
            "isPrimaryListing": bool(row.get("is_primary_listing")),
            "sector": self._first_text(metadata.get("sector"), row.get("sector")),
            "industry": self._first_text(
                metadata.get("industry"),
                row.get("industry"),
            ),
            "currency": currency,
            "marketCap": market_cap_usd,
            "marketCapLocal": market_cap_local,
            "marketCapCurrency": currency,
            "sourceProvider": self._metadata_service.source_id,
            "retrievedAt": datetime.now(timezone.utc).isoformat(),
            "isActive": bool(row.get("is_active", 1)),
        }

    def _first_text(self, *values: Any) -> str | None:
        for value in values:
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized
        return None

    def _positive_number(self, value: Any) -> bool:
        return self._positive_value(value) is not None

    def _positive_value(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result or result <= 0:
            return None
        return result
