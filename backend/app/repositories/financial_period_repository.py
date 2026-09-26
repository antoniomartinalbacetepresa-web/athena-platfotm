from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class FinancialPeriodSaveStats:
    received: int
    inserted: int
    unchanged: int


class FinancialPeriodRepository:
    """Immutable PIT storage for comparable issuer financial periods."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def save_many(self, *, instrument_id: int, periods: list[dict], source_provider: str, retrieved_at: datetime) -> FinancialPeriodSaveStats:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        provider = self._text(source_provider, "source_provider")
        retrieved = self._utc_iso(retrieved_at, "retrieved_at")
        retrieved_dt = datetime.fromisoformat(retrieved)
        normalized = [self._normalize(item) for item in periods]
        self._database.initialize()
        inserted = 0
        with self._database.connect() as connection:
            for item in normalized:
                source_ts = item["source_timestamp"]
                if source_ts is not None and datetime.fromisoformat(source_ts) > retrieved_dt:
                    raise ValueError("source_timestamp no puede ser posterior a retrieved_at.")
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO financial_periods
                    (instrument_id, period_start, period_end, currency, net_income, free_cash_flow,
                     source_provider, source_timestamp, retrieved_at, dividends_paid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (instrument_id, item["period_start"], item["period_end"], item["currency"],
                     item["net_income"], item["free_cash_flow"], provider, source_ts, retrieved,
                     item["dividends_paid"]),
                )
                inserted += 1 if cursor.rowcount == 1 else 0
        return FinancialPeriodSaveStats(len(normalized), inserted, len(normalized) - inserted)

    def list_for_instrument(self, instrument_id: int, *, knowledge_cutoff: datetime) -> list[dict]:
        """Return every immutable revision visible at the PIT cutoff."""
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        cutoff = self._utc_iso(knowledge_cutoff, "knowledge_cutoff")
        self._database.initialize()
        with self._database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM financial_periods
                WHERE instrument_id = ? AND retrieved_at <= ? AND period_end <= ?
                ORDER BY period_end ASC, retrieved_at ASC, id ASC""",
                (instrument_id, cutoff, cutoff),
            ).fetchall()
        result = [dict(row) for row in rows]
        if any(row["retrieved_at"] > cutoff or row["period_end"] > cutoff for row in result):
            raise RuntimeError("Un periodo financiero posterior al knowledge_cutoff atravesó el filtro PIT.")
        return result

    def list_latest_for_instrument(self, instrument_id: int, *, knowledge_cutoff: datetime) -> list[dict]:
        """Return one latest-known revision per economic period/provider at the cutoff."""
        rows = self.list_for_instrument(instrument_id, knowledge_cutoff=knowledge_cutoff)
        latest: dict[tuple[str, str, str, str], dict] = {}
        for row in rows:
            key = (row["period_start"], row["period_end"], row["currency"], row["source_provider"])
            current = latest.get(key)
            if current is None or (row["retrieved_at"], row["id"]) > (current["retrieved_at"], current["id"]):
                latest[key] = row
        return sorted(latest.values(), key=lambda row: (row["period_end"], row["source_provider"], row["id"]))

    def _normalize(self, value: dict) -> dict:
        start = self._date(value.get("period_start"), "period_start")
        end = self._date(value.get("period_end"), "period_end")
        if datetime.fromisoformat(start) > datetime.fromisoformat(end):
            raise ValueError("period_start no puede ser posterior a period_end.")
        currency = self._text(value.get("currency"), "currency").upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise ValueError("currency debe ser un código ISO de tres letras.")
        net_income = self._number(value.get("net_income"), "net_income")
        free_cash_flow = self._number(value.get("free_cash_flow"), "free_cash_flow")
        dividends_paid = self._number(value.get("dividends_paid"), "dividends_paid")
        if dividends_paid is not None and dividends_paid < 0:
            raise ValueError("dividends_paid no puede ser negativo.")
        if net_income is None and free_cash_flow is None:
            raise ValueError("net_income o free_cash_flow es obligatorio.")
        source_raw = value.get("source_timestamp")
        source_timestamp = None if source_raw is None else self._date(source_raw, "source_timestamp")
        return {"period_start": start, "period_end": end, "currency": currency,
                "net_income": net_income, "free_cash_flow": free_cash_flow,
                "dividends_paid": dividends_paid, "source_timestamp": source_timestamp}

    @staticmethod
    def _number(value: object, field: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field} debe ser finito.")
        return number

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value).strip() if value is not None else ""
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _date(value: object, field: str) -> str:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{field} no contiene una fecha ISO válida.") from exc
        else:
            raise ValueError(f"{field} es obligatorio.")
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return dt.astimezone(timezone.utc).isoformat()

    _utc_iso = _date
