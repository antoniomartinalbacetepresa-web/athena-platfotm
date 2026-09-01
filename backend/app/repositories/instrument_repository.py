from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class InstrumentUpsertStats:
    processed: int
    inserted: int
    updated: int
    unchanged: int
    instrument_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.processed < 0:
            raise ValueError(
                "processed no puede ser negativo."
            )

        if self.inserted < 0:
            raise ValueError(
                "inserted no puede ser negativo."
            )

        if self.updated < 0:
            raise ValueError(
                "updated no puede ser negativo."
            )

        if self.unchanged < 0:
            raise ValueError(
                "unchanged no puede ser negativo."
            )

        if (
            self.inserted
            + self.updated
            + self.unchanged
            != self.processed
        ):
            raise ValueError(
                "Las estadísticas de upsert "
                "no son consistentes."
            )

        if len(self.instrument_ids) != self.processed:
            raise ValueError(
                "instrument_ids debe contener "
                "un identificador por instrumento procesado."
            )


class InstrumentRepository:
    _COMPARABLE_FIELDS = (
        "company_name",
        "issuer_id",
        "instrument_id",
        "country",
        "region_key",
        "exchange",
        "instrument_type",
        "is_primary_listing",
        "sector",
        "industry",
        "currency",
        "market_cap_usd",
        "market_cap_local",
        "market_cap_local_currency",
        "source_provider",
        "source_timestamp",
        "is_active",
    )

    def __init__(
        self,
        database: AthenaDatabase | None = None,
    ) -> None:
        self._database = (
            database
            if database is not None
            else AthenaDatabase()
        )

    def upsert(
        self,
        instrument: dict[str, Any],
    ) -> int:
        normalized = self._normalize_instrument(
            instrument
        )

        with self._database.connect() as connection:
            instrument_id = self._upsert_with_connection(
                connection=connection,
                instrument=normalized,
            )

        return instrument_id

    def upsert_many(
        self,
        instruments: Iterable[dict[str, Any]],
    ) -> list[int]:
        normalized_instruments = [
            self._normalize_instrument(instrument)
            for instrument in instruments
        ]

        instrument_ids: list[int] = []

        with self._database.connect() as connection:
            for instrument in normalized_instruments:
                instrument_id = self._upsert_with_connection(
                    connection=connection,
                    instrument=instrument,
                )

                instrument_ids.append(
                    instrument_id
                )

        return instrument_ids

    def upsert_many_with_stats(
        self,
        instruments: Iterable[dict[str, Any]],
    ) -> InstrumentUpsertStats:
        normalized_instruments = [
            self._normalize_instrument(instrument)
            for instrument in instruments
        ]

        instrument_ids: list[int] = []

        inserted = 0
        updated = 0
        unchanged = 0

        with self._database.connect() as connection:
            for instrument in normalized_instruments:
                existing_row = self._find_existing_row(
                    connection=connection,
                    symbol=instrument["symbol"],
                    exchange_short_name=instrument[
                        "exchange_short_name"
                    ],
                )

                if existing_row is None:
                    instrument_id = self._insert_with_connection(
                        connection=connection,
                        instrument=instrument,
                    )

                    inserted += 1
                else:
                    instrument_id = int(
                        existing_row["id"]
                    )

                    has_changes = self._has_material_changes(
                        existing_row=existing_row,
                        instrument=instrument,
                    )

                    self._update_with_connection(
                        connection=connection,
                        instrument_id=instrument_id,
                        instrument=instrument,
                    )

                    if has_changes:
                        updated += 1
                    else:
                        unchanged += 1

                instrument_ids.append(
                    instrument_id
                )

        return InstrumentUpsertStats(
            processed=len(
                normalized_instruments
            ),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            instrument_ids=tuple(
                instrument_ids
            ),
        )

    def deactivate_missing_for_source(
        self,
        source_provider: str,
        active_listings: Iterable[
            tuple[str, str | None]
        ],
    ) -> int:
        normalized_source_provider = (
            self._normalize_required_text(
                source_provider,
                "source_provider",
            )
        )

        normalized_active_listings = {
            (
                self._normalize_required_text(
                    symbol,
                    "symbol",
                ).upper(),
                self._normalize_upper_optional_text(
                    exchange_short_name
                ),
            )
            for symbol, exchange_short_name
            in active_listings
        }

        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    symbol,
                    exchange_short_name
                FROM instruments
                WHERE source_provider = ?
                  AND is_active = 1
                """,
                (
                    normalized_source_provider,
                ),
            ).fetchall()

            instrument_ids_to_deactivate = [
                int(row["id"])
                for row in rows
                if (
                    row["symbol"],
                    row["exchange_short_name"],
                )
                not in normalized_active_listings
            ]

            if not instrument_ids_to_deactivate:
                return 0

            connection.executemany(
                """
                UPDATE instruments
                SET
                    is_active = 0,
                    updated_at = ?
                WHERE id = ?
                  AND is_active = 1
                """,
                [
                    (
                        now,
                        instrument_id,
                    )
                    for instrument_id
                    in instrument_ids_to_deactivate
                ],
            )

        return len(
            instrument_ids_to_deactivate
        )

    def count_active_for_source(
        self,
        source_provider: str,
    ) -> int:
        normalized_source_provider = (
            self._normalize_required_text(
                source_provider,
                "source_provider",
            )
        )

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM instruments
                WHERE source_provider = ?
                  AND is_active = 1
                """,
                (
                    normalized_source_provider,
                ),
            ).fetchone()

        if row is None:
            return 0

        return int(
            row["total"]
        )

    def get_by_id(
        self,
        instrument_id: int,
    ) -> dict[str, Any] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM instruments
                WHERE id = ?
                """,
                (
                    instrument_id,
                ),
            ).fetchone()

        return self._row_to_dict(row)

    def get_by_listing(
        self,
        symbol: str,
        exchange_short_name: str | None,
    ) -> dict[str, Any] | None:
        normalized_symbol = self._normalize_required_text(
            symbol,
            "symbol",
        ).upper()

        normalized_exchange = self._normalize_upper_optional_text(
            exchange_short_name
        )

        with self._database.connect() as connection:
            row = self._find_existing_row(
                connection=connection,
                symbol=normalized_symbol,
                exchange_short_name=normalized_exchange,
            )

        return self._row_to_dict(row)

    def count(
        self,
        active_only: bool = False,
    ) -> int:
        with self._database.connect() as connection:
            if active_only:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM instruments
                    WHERE is_active = 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM instruments
                    """
                ).fetchone()

        if row is None:
            return 0

        return int(row["total"])

    def _upsert_with_connection(
        self,
        connection: sqlite3.Connection,
        instrument: dict[str, Any],
    ) -> int:
        existing_row = self._find_existing_row(
            connection=connection,
            symbol=instrument["symbol"],
            exchange_short_name=instrument[
                "exchange_short_name"
            ],
        )

        if existing_row is None:
            return self._insert_with_connection(
                connection=connection,
                instrument=instrument,
            )

        existing_id = int(
            existing_row["id"]
        )

        self._update_with_connection(
            connection=connection,
            instrument_id=existing_id,
            instrument=instrument,
        )

        return existing_id

    def _insert_with_connection(
        self,
        connection: sqlite3.Connection,
        instrument: dict[str, Any],
    ) -> int:
        now = datetime.now(
            timezone.utc
        ).isoformat()

        cursor = connection.execute(
            """
            INSERT INTO instruments (
                symbol,
                company_name,
                issuer_id,
                instrument_id,
                country,
                region_key,
                exchange,
                exchange_short_name,
                instrument_type,
                is_primary_listing,
                sector,
                industry,
                currency,
                market_cap_usd,
                market_cap_local,
                market_cap_local_currency,
                source_provider,
                source_timestamp,
                retrieved_at,
                is_active,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                instrument["symbol"],
                instrument["company_name"],
                instrument["issuer_id"],
                instrument["instrument_id"],
                instrument["country"],
                instrument["region_key"],
                instrument["exchange"],
                instrument["exchange_short_name"],
                instrument["instrument_type"],
                instrument["is_primary_listing"],
                instrument["sector"],
                instrument["industry"],
                instrument["currency"],
                instrument["market_cap_usd"],
                instrument["market_cap_local"],
                instrument["market_cap_local_currency"],
                instrument["source_provider"],
                instrument["source_timestamp"],
                instrument["retrieved_at"],
                instrument["is_active"],
                now,
                now,
            ),
        )

        if cursor.lastrowid is None:
            raise RuntimeError(
                "No se pudo obtener el identificador "
                "del instrumento creado."
            )

        return int(
            cursor.lastrowid
        )

    def _update_with_connection(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        instrument: dict[str, Any],
    ) -> None:
        now = datetime.now(
            timezone.utc
        ).isoformat()

        connection.execute(
            """
            UPDATE instruments
            SET
                company_name = ?,
                issuer_id = ?,
                instrument_id = ?,
                country = ?,
                region_key = ?,
                exchange = ?,
                instrument_type = ?,
                is_primary_listing = ?,
                sector = ?,
                industry = ?,
                currency = ?,
                market_cap_usd = ?,
                market_cap_local = ?,
                market_cap_local_currency = ?,
                source_provider = ?,
                source_timestamp = ?,
                retrieved_at = ?,
                is_active = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                instrument["company_name"],
                instrument["issuer_id"],
                instrument["instrument_id"],
                instrument["country"],
                instrument["region_key"],
                instrument["exchange"],
                instrument["instrument_type"],
                instrument["is_primary_listing"],
                instrument["sector"],
                instrument["industry"],
                instrument["currency"],
                instrument["market_cap_usd"],
                instrument["market_cap_local"],
                instrument["market_cap_local_currency"],
                instrument["source_provider"],
                instrument["source_timestamp"],
                instrument["retrieved_at"],
                instrument["is_active"],
                now,
                instrument_id,
            ),
        )

    def _has_material_changes(
        self,
        existing_row: sqlite3.Row,
        instrument: dict[str, Any],
    ) -> bool:
        for field in self._COMPARABLE_FIELDS:
            if existing_row[field] != instrument[field]:
                return True

        return False

    def _find_existing_row(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        exchange_short_name: str | None,
    ) -> sqlite3.Row | None:
        if exchange_short_name is None:
            return connection.execute(
                """
                SELECT *
                FROM instruments
                WHERE symbol = ?
                  AND exchange_short_name IS NULL
                """,
                (
                    symbol,
                ),
            ).fetchone()

        return connection.execute(
            """
            SELECT *
            FROM instruments
            WHERE symbol = ?
              AND exchange_short_name = ?
            """,
            (
                symbol,
                exchange_short_name,
            ),
        ).fetchone()

    def _find_existing_id(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        exchange_short_name: str | None,
    ) -> int | None:
        row = self._find_existing_row(
            connection=connection,
            symbol=symbol,
            exchange_short_name=exchange_short_name,
        )

        if row is None:
            return None

        return int(
            row["id"]
        )

    def _normalize_instrument(
        self,
        instrument: dict[str, Any],
    ) -> dict[str, Any]:
        symbol = self._normalize_required_text(
            instrument.get("symbol"),
            "symbol",
        ).upper()

        company_name = self._normalize_required_text(
            instrument.get("companyName"),
            "companyName",
        )

        exchange_short_name = self._normalize_upper_optional_text(
            instrument.get("exchangeShortName")
        )

        return {
            "symbol": symbol,
            "company_name": company_name,
            "issuer_id": self._normalize_optional_text(
                instrument.get("issuerId")
            ),
            "instrument_id": self._normalize_optional_text(
                instrument.get("instrumentId")
            ),
            "country": self._normalize_optional_text(
                instrument.get("country")
            ),
            "region_key": self._normalize_optional_text(
                instrument.get("regionKey")
            ),
            "exchange": self._normalize_optional_text(
                instrument.get("exchange")
            ),
            "exchange_short_name": exchange_short_name,
            "instrument_type": (
                self._normalize_optional_text(
                    instrument.get("instrumentType")
                )
                or "unknown"
            ),
            "is_primary_listing": self._normalize_bool(
                instrument.get("isPrimaryListing")
            ),
            "sector": self._normalize_optional_text(
                instrument.get("sector")
            ),
            "industry": self._normalize_optional_text(
                instrument.get("industry")
            ),
            "currency": self._normalize_upper_optional_text(
                instrument.get("currency")
            ),
            "market_cap_usd": self._normalize_positive_float(
                instrument.get("marketCap")
            ),
            "market_cap_local": self._normalize_positive_float(
                instrument.get("marketCapLocal")
            ),
            "market_cap_local_currency": (
                self._normalize_upper_optional_text(
                    instrument.get("currency")
                )
            ),
            "source_provider": self._normalize_optional_text(
                instrument.get("sourceProvider")
            ),
            "source_timestamp": self._normalize_optional_text(
                instrument.get("sourceTimestamp")
            ),
            "retrieved_at": self._normalize_optional_text(
                instrument.get("retrievedAt")
            ),
            "is_active": self._normalize_bool(
                instrument.get(
                    "isActive",
                    True,
                )
            ),
        }

    def _normalize_required_text(
        self,
        value: Any,
        field_name: str,
    ) -> str:
        if value is None:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                f"{field_name} es obligatorio."
            )

        return normalized

    def _normalize_optional_text(
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

    def _normalize_upper_optional_text(
        self,
        value: Any,
    ) -> str | None:
        normalized = self._normalize_optional_text(
            value
        )

        if normalized is None:
            return None

        return normalized.upper()

    def _normalize_positive_float(
        self,
        value: Any,
    ) -> float | None:
        if value is None:
            return None

        try:
            result = float(
                value
            )
        except (TypeError, ValueError):
            return None

        if result != result:
            return None

        if result <= 0:
            return None

        return result

    def _normalize_bool(
        self,
        value: Any,
    ) -> int:
        if isinstance(
            value,
            bool,
        ):
            return 1 if value else 0

        if isinstance(
            value,
            (int, float),
        ):
            return 1 if value != 0 else 0

        if isinstance(
            value,
            str,
        ):
            normalized = value.strip().lower()

            if normalized in {
                "true",
                "1",
                "yes",
                "y",
            }:
                return 1

            if normalized in {
                "false",
                "0",
                "no",
                "n",
                "",
            }:
                return 0

        return 0

    def _row_to_dict(
        self,
        row: sqlite3.Row | None,
    ) -> dict[str, Any] | None:
        if row is None:
            return None

        return dict(
            row
        )
