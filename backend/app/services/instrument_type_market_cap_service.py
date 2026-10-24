from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class InstrumentTypeMarketCapReport:
    listing_count: int
    total_market_cap_usd: float
    by_type: dict[str, dict[str, float | int]]
    equity_like_market_cap_usd: float
    non_equity_market_cap_usd: float
    unknown_market_cap_usd: float

    @property
    def equity_like_market_cap_share(self) -> float:
        return self._share(self.equity_like_market_cap_usd)

    @property
    def non_equity_market_cap_share(self) -> float:
        return self._share(self.non_equity_market_cap_usd)

    @property
    def unknown_market_cap_share(self) -> float:
        return self._share(self.unknown_market_cap_usd)

    def _share(self, value: float) -> float:
        if self.total_market_cap_usd <= 0:
            return 0.0
        return value / self.total_market_cap_usd

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": "diagnostic_only",
            "listingCount": self.listing_count,
            "totalMarketCapUsd": self.total_market_cap_usd,
            "byType": {
                key: dict(value)
                for key, value in sorted(self.by_type.items())
            },
            "equityLikeMarketCapUsd": self.equity_like_market_cap_usd,
            "equityLikeMarketCapShare": self.equity_like_market_cap_share,
            "nonEquityMarketCapUsd": self.non_equity_market_cap_usd,
            "nonEquityMarketCapShare": self.non_equity_market_cap_share,
            "unknownMarketCapUsd": self.unknown_market_cap_usd,
            "unknownMarketCapShare": self.unknown_market_cap_share,
            "warning": (
                "Este informe mide la composición del catálogo por tipo de "
                "instrumento. No elimina registros ni habilita pesos regionales."
            ),
        }


class InstrumentTypeMarketCapService:
    EQUITY_LIKE_TYPES = frozenset(
        {
            "common_stock",
            "preferred_stock",
            "adr",
            "cdr",
            "sdr",
            "depositary_receipt",
        }
    )
    NON_EQUITY_TYPES = frozenset({"etf", "fund"})

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def get_report(self) -> InstrumentTypeMarketCapReport:
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    LOWER(TRIM(COALESCE(instrument_type, 'unknown'))) AS type_key,
                    COUNT(*) AS listing_count,
                    COALESCE(SUM(market_cap_usd), 0) AS market_cap_usd
                FROM instruments
                WHERE is_active = 1
                  AND market_cap_usd IS NOT NULL
                  AND market_cap_usd > 0
                GROUP BY LOWER(TRIM(COALESCE(instrument_type, 'unknown')))
                ORDER BY type_key
                """
            ).fetchall()

        by_type: dict[str, dict[str, float | int]] = {}
        listing_count = 0
        total_market_cap = 0.0
        equity_like_market_cap = 0.0
        non_equity_market_cap = 0.0
        unknown_market_cap = 0.0

        for row in rows:
            type_key = str(row["type_key"] or "unknown").strip() or "unknown"
            count = int(row["listing_count"])
            market_cap = float(row["market_cap_usd"])
            listing_count += count
            total_market_cap += market_cap
            by_type[type_key] = {
                "listingCount": count,
                "marketCapUsd": market_cap,
            }

            if type_key in self.EQUITY_LIKE_TYPES:
                equity_like_market_cap += market_cap
            elif type_key in self.NON_EQUITY_TYPES:
                non_equity_market_cap += market_cap
            else:
                unknown_market_cap += market_cap

        if total_market_cap > 0:
            for values in by_type.values():
                values["marketCapShare"] = (
                    float(values["marketCapUsd"]) / total_market_cap
                )

        return InstrumentTypeMarketCapReport(
            listing_count=listing_count,
            total_market_cap_usd=total_market_cap,
            by_type=by_type,
            equity_like_market_cap_usd=equity_like_market_cap,
            non_equity_market_cap_usd=non_equity_market_cap,
            unknown_market_cap_usd=unknown_market_cap,
        )
