from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class FxRateRecord:
    id: int
    observed_on: date
    base_currency: str
    quote_currency: str
    rate: float
    source_provider: str
    source_symbol: str | None
    observed_at: datetime
    retrieved_at: datetime


class FxRateRepository:
    """Persist immutable FX observations and replay only what was knowable PIT."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def save(
        self,
        *,
        observed_on: date,
        base_currency: str,
        quote_currency: str,
        rate: float,
        source_provider: str,
        source_symbol: str | None,
        observed_at: datetime,
        retrieved_at: datetime,
    ) -> FxRateRecord:
        target_date = self._date(observed_on, "observed_on")
        base = self._currency(base_currency, "base_currency")
        quote = self._currency(quote_currency, "quote_currency")
        normalized_rate = self._positive_finite(rate)
        provider = self._required_text(source_provider, "source_provider")
        symbol = self._optional_text(source_symbol)
        observed = self._aware_utc(observed_at, "observed_at")
        retrieved = self._aware_utc(retrieved_at, "retrieved_at")

        if observed.date() != target_date:
            raise ValueError("observed_at debe pertenecer a observed_on.")
        if retrieved < observed:
            raise ValueError("retrieved_at no puede preceder a observed_at.")

        self._database.initialize()
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, date, base_currency, quote_currency, rate, source,
                       source_symbol, source_timestamp, retrieved_at
                FROM fx_rates
                WHERE date = ? AND base_currency = ? AND quote_currency = ? AND source = ?
                """,
                (target_date.isoformat(), base, quote, provider),
            ).fetchone()

            if existing is not None:
                record = self._record(existing)
                self._assert_same_immutable_observation(
                    record=record,
                    rate=normalized_rate,
                    source_symbol=symbol,
                    observed_at=observed,
                    retrieved_at=retrieved,
                )
                return record

            cursor = connection.execute(
                """
                INSERT INTO fx_rates (
                    date, base_currency, quote_currency, rate, source,
                    source_symbol, source_timestamp, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_date.isoformat(),
                    base,
                    quote,
                    normalized_rate,
                    provider,
                    symbol,
                    observed.isoformat(),
                    retrieved.isoformat(),
                ),
            )
            row = connection.execute(
                """
                SELECT id, date, base_currency, quote_currency, rate, source,
                       source_symbol, source_timestamp, retrieved_at
                FROM fx_rates WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            if row is None:
                raise RuntimeError("No se pudo verificar la observación FX persistida.")
            return self._record(row)

    def get_pit(
        self,
        *,
        observed_on: date,
        base_currency: str,
        quote_currency: str,
        source_symbol: str,
        knowledge_cutoff: datetime,
    ) -> FxRateRecord | None:
        target_date = self._date(observed_on, "observed_on")
        base = self._currency(base_currency, "base_currency")
        quote = self._currency(quote_currency, "quote_currency")
        symbol = self._required_text(source_symbol, "source_symbol")
        cutoff = self._aware_utc(knowledge_cutoff, "knowledge_cutoff")

        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, date, base_currency, quote_currency, rate, source,
                       source_symbol, source_timestamp, retrieved_at
                FROM fx_rates
                WHERE date = ?
                  AND base_currency = ?
                  AND quote_currency = ?
                  AND source_symbol = ?
                  AND source_timestamp IS NOT NULL
                  AND source_timestamp <= ?
                  AND retrieved_at <= ?
                ORDER BY retrieved_at ASC, id ASC
                LIMIT 2
                """,
                (
                    target_date.isoformat(),
                    base,
                    quote,
                    symbol,
                    cutoff.isoformat(),
                    cutoff.isoformat(),
                ),
            ).fetchall()

        if not rows:
            return None
        if len(rows) != 1:
            raise RuntimeError(
                "Existen varias observaciones FX PIT elegibles y no puede elegirse una fuente sin ambigüedad."
            )
        return self._record(rows[0])

    def _assert_same_immutable_observation(
        self,
        *,
        record: FxRateRecord,
        rate: float,
        source_symbol: str | None,
        observed_at: datetime,
        retrieved_at: datetime,
    ) -> None:
        if (
            record.rate != rate
            or record.source_symbol != source_symbol
            or record.observed_at != observed_at
            or record.retrieved_at != retrieved_at
        ):
            raise RuntimeError(
                "Conflicto de integridad: una observación FX persistida no puede sobrescribirse."
            )

    def _record(self, row: Any) -> FxRateRecord:
        observed_raw = row[7]
        if observed_raw is None:
            raise RuntimeError("La observación FX persistida carece de observed_at.")
        record = FxRateRecord(
            id=int(row[0]),
            observed_on=date.fromisoformat(str(row[1])),
            base_currency=self._currency(str(row[2]), "base_currency"),
            quote_currency=self._currency(str(row[3]), "quote_currency"),
            rate=self._positive_finite(row[4]),
            source_provider=self._required_text(str(row[5]), "source_provider"),
            source_symbol=self._optional_text(row[6]),
            observed_at=self._aware_utc(
                datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00")),
                "observed_at",
            ),
            retrieved_at=self._aware_utc(
                datetime.fromisoformat(str(row[8]).replace("Z", "+00:00")),
                "retrieved_at",
            ),
        )
        if record.observed_at.date() != record.observed_on:
            raise RuntimeError("La observación FX persistida viola su fecha observada.")
        if record.retrieved_at < record.observed_at:
            raise RuntimeError("La observación FX persistida viola el orden temporal PIT.")
        return record

    def _currency(self, value: object, field: str) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError(f"{field} debe ser un código ISO de tres letras.")
        return normalized

    def _date(self, value: object, field: str) -> date:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise ValueError(f"{field} debe ser una fecha sin hora.")
        return value

    def _positive_finite(self, value: object) -> float:
        if isinstance(value, bool):
            raise ValueError("rate debe ser numérico, positivo y finito.")
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("rate debe ser numérico, positivo y finito.") from exc
        if not isfinite(parsed) or parsed <= 0:
            raise ValueError("rate debe ser numérico, positivo y finito.")
        return parsed

    def _aware_utc(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
