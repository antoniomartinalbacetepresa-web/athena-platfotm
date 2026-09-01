from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository


@dataclass(frozen=True)
class MarketCapCoverageReport:
    usable_count: int
    total_market_cap_usd: float
    top_market_cap_shares: dict[str, float]
    region_market_cap_usd: dict[str, float]
    region_weights: dict[str, float]
    country_market_cap_usd: dict[str, float]
    currency_market_cap_usd: dict[str, float]
    top_assets: tuple[dict[str, Any], ...]
    heuristic_unique_company_count: int
    heuristic_duplicate_group_count: int
    heuristic_deduplicated_total_market_cap_usd: float
    heuristic_duplicate_excess_market_cap_usd: float
    heuristic_top_duplicate_groups: tuple[dict[str, Any], ...]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "usableCount": self.usable_count,
            "totalMarketCapUsd": self.total_market_cap_usd,
            "topMarketCapShares": dict(self.top_market_cap_shares),
            "regionMarketCapUsd": dict(self.region_market_cap_usd),
            "regionWeights": dict(self.region_weights),
            "countryMarketCapUsd": dict(self.country_market_cap_usd),
            "currencyMarketCapUsd": dict(self.currency_market_cap_usd),
            "topAssets": [dict(asset) for asset in self.top_assets],
            "heuristicIssuerDeduplication": {
                "status": "diagnostic_only",
                "method": "exact_normalized_company_name_keep_largest_market_cap",
                "warning": (
                    "No es una identidad de emisor definitiva. Los nombres de empresa "
                    "pueden unir o separar valores incorrectamente."
                ),
                "uniqueCompanyCount": self.heuristic_unique_company_count,
                "duplicateGroupCount": self.heuristic_duplicate_group_count,
                "deduplicatedTotalMarketCapUsd": (
                    self.heuristic_deduplicated_total_market_cap_usd
                ),
                "duplicateExcessMarketCapUsd": (
                    self.heuristic_duplicate_excess_market_cap_usd
                ),
                "topDuplicateGroups": [
                    dict(group) for group in self.heuristic_top_duplicate_groups
                ],
            },
        }


class MarketCapCoverageService:
    """Analiza concentración y distribución del market cap persistido.

    El informe es diagnóstico. No certifica que la muestra sea representativa
    ni resuelve de forma definitiva dobles listados de un mismo emisor.
    """

    _REGIONS = ("america", "europe", "asia")
    _TOP_BUCKETS = (10, 50, 100, 500, 1000)
    _TOP_ASSET_COUNT = 50
    _TOP_DUPLICATE_GROUP_COUNT = 50

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = InstrumentRepository(database=self._database)

    def get_report(self) -> MarketCapCoverageReport:
        self._database.initialize()
        rows = self._repository.list_active()

        usable: list[dict[str, Any]] = []
        region_market_cap = {region: 0.0 for region in self._REGIONS}
        country_market_cap: dict[str, float] = {}
        currency_market_cap: dict[str, float] = {}

        for row in rows:
            market_cap = row.get("market_cap_usd")
            region = str(row.get("region_key") or "").strip().lower()
            country = str(row.get("country") or "").strip()

            if (
                not isinstance(market_cap, (int, float))
                or market_cap <= 0
                or not country
                or region not in region_market_cap
            ):
                continue

            cap = float(market_cap)
            currency = str(
                row.get("market_cap_local_currency")
                or row.get("currency")
                or "unknown"
            ).strip().upper() or "UNKNOWN"

            asset = {
                "symbol": str(row.get("symbol") or "").strip(),
                "companyName": str(row.get("company_name") or "").strip(),
                "country": country,
                "regionKey": region,
                "exchange": str(
                    row.get("exchange_short_name")
                    or row.get("exchange")
                    or ""
                ).strip(),
                "currency": currency,
                "marketCapUsd": cap,
                "marketCapLocal": row.get("market_cap_local"),
            }
            usable.append(asset)

            region_market_cap[region] += cap
            country_market_cap[country] = (
                country_market_cap.get(country, 0.0) + cap
            )
            currency_market_cap[currency] = (
                currency_market_cap.get(currency, 0.0) + cap
            )

        usable.sort(key=lambda item: item["marketCapUsd"], reverse=True)
        total_market_cap = sum(
            float(asset["marketCapUsd"])
            for asset in usable
        )

        top_shares = self._build_top_shares(
            usable=usable,
            total_market_cap=total_market_cap,
        )

        region_weights = {
            region: (
                market_cap / total_market_cap
                if total_market_cap > 0
                else 0.0
            )
            for region, market_cap in region_market_cap.items()
        }

        ordered_country_market_cap = dict(
            sorted(
                country_market_cap.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        )
        ordered_currency_market_cap = dict(
            sorted(
                currency_market_cap.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        )

        issuer_diagnostics = self._build_heuristic_issuer_diagnostics(usable)

        return MarketCapCoverageReport(
            usable_count=len(usable),
            total_market_cap_usd=total_market_cap,
            top_market_cap_shares=top_shares,
            region_market_cap_usd=region_market_cap,
            region_weights=region_weights,
            country_market_cap_usd=ordered_country_market_cap,
            currency_market_cap_usd=ordered_currency_market_cap,
            top_assets=tuple(usable[: self._TOP_ASSET_COUNT]),
            heuristic_unique_company_count=issuer_diagnostics["unique_count"],
            heuristic_duplicate_group_count=issuer_diagnostics[
                "duplicate_group_count"
            ],
            heuristic_deduplicated_total_market_cap_usd=issuer_diagnostics[
                "deduplicated_total"
            ],
            heuristic_duplicate_excess_market_cap_usd=issuer_diagnostics[
                "duplicate_excess"
            ],
            heuristic_top_duplicate_groups=tuple(
                issuer_diagnostics["top_duplicate_groups"]
            ),
        )

    def _build_top_shares(
        self,
        *,
        usable: list[dict[str, Any]],
        total_market_cap: float,
    ) -> dict[str, float]:
        top_shares: dict[str, float] = {}
        if total_market_cap <= 0:
            return top_shares

        cumulative = 0.0
        bucket_index = 0
        for index, asset in enumerate(usable, start=1):
            cumulative += float(asset["marketCapUsd"])
            while (
                bucket_index < len(self._TOP_BUCKETS)
                and index == self._TOP_BUCKETS[bucket_index]
            ):
                bucket = self._TOP_BUCKETS[bucket_index]
                top_shares[f"top{bucket}"] = cumulative / total_market_cap
                bucket_index += 1

        for bucket in self._TOP_BUCKETS:
            key = f"top{bucket}"
            if key not in top_shares:
                top_shares[key] = 1.0 if usable else 0.0

        return top_shares

    def _build_heuristic_issuer_diagnostics(
        self,
        usable: list[dict[str, Any]],
    ) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        unnamed_index = 0

        for asset in usable:
            company_name = str(asset.get("companyName") or "").strip()
            normalized_name = self._normalize_company_name(company_name)
            if not normalized_name:
                unnamed_index += 1
                normalized_name = f"__unnamed__{unnamed_index}"
            groups.setdefault(normalized_name, []).append(asset)

        deduplicated_total = 0.0
        duplicate_groups: list[dict[str, Any]] = []

        for assets in groups.values():
            ordered = sorted(
                assets,
                key=lambda item: float(item["marketCapUsd"]),
                reverse=True,
            )
            representative_cap = float(ordered[0]["marketCapUsd"])
            observed_cap = sum(float(item["marketCapUsd"]) for item in ordered)
            deduplicated_total += representative_cap

            if len(ordered) <= 1:
                continue

            duplicate_groups.append(
                {
                    "companyName": ordered[0]["companyName"],
                    "listingCount": len(ordered),
                    "observedMarketCapUsd": observed_cap,
                    "representativeMarketCapUsd": representative_cap,
                    "duplicateExcessMarketCapUsd": (
                        observed_cap - representative_cap
                    ),
                    "symbols": [
                        str(item["symbol"])
                        for item in ordered[:20]
                    ],
                    "countries": sorted(
                        {
                            str(item["country"])
                            for item in ordered
                            if str(item["country"])
                        }
                    ),
                }
            )

        duplicate_groups.sort(
            key=lambda item: float(item["duplicateExcessMarketCapUsd"]),
            reverse=True,
        )

        raw_total = sum(float(asset["marketCapUsd"]) for asset in usable)
        return {
            "unique_count": len(groups),
            "duplicate_group_count": len(duplicate_groups),
            "deduplicated_total": deduplicated_total,
            "duplicate_excess": max(0.0, raw_total - deduplicated_total),
            "top_duplicate_groups": duplicate_groups[
                : self._TOP_DUPLICATE_GROUP_COUNT
            ],
        }

    def _normalize_company_name(self, value: str) -> str:
        return " ".join(value.casefold().split())
