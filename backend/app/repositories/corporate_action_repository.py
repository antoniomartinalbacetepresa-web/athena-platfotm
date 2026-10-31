from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class CorporateActionSaveStats:
    received: int
    inserted: int
    unchanged: int


class CorporateActionRepository:
    """Durable, immutable PIT store for corporate actions.

    effective_at describes when the action applies economically.
    retrieved_at describes when ATHENA learned the action. Historical paid-action
    views constrain both timestamps to the knowledge cutoff. Declared-future views
    constrain retrieved_at to the cutoff while requiring effective_at afterwards.
    """

    _VALID_TYPES = {"dividend", "split"}

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def require_instrument_symbol(self, *, instrument_id: int, symbol: str) -> None:
        """Fail closed if a provider symbol is not the instrument's stored identity.

        A correct provider response must not be persisted under an unrelated
        instrument_id, even when the provider returns no corporate actions.
        """
        if isinstance(instrument_id, bool) or not isinstance(instrument_id, int) or instrument_id <= 0:
            raise ValueError("instrument_id debe ser un entero positivo.")
        expected_symbol = self._required_text(symbol, "symbol").upper()
        self._database.initialize()
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT symbol FROM instruments WHERE id = ?", (instrument_id,)
            ).fetchone()
        if row is None:
            raise ValueError("instrument_id no corresponde a un instrumento existente.")
        actual_symbol = self._required_text(row["symbol"], "instrument.symbol").upper()
        if actual_symbol != expected_symbol:
            raise ValueError("instrument_id y symbol no corresponden al mismo instrumento.")

    def save_many(self, *, instrument_id: int, actions: Iterable[dict[str, Any]], source_provider: str, retrieved_at: datetime, captured_by_athena: bool = False) -> CorporateActionSaveStats:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        provider = self._required_text(source_provider, "source_provider")
        retrieved = self._utc_iso(retrieved_at, "retrieved_at")
        retrieved_dt = datetime.fromisoformat(retrieved)
        buffered = list(actions)
        self._initialize_schema()
        inserted = 0
        with self._database.connect() as connection:
            for action in buffered:
                normalized = self._normalize_action(action)
                effective_dt = datetime.fromisoformat(normalized["effective_at"])
                source_timestamp = normalized["source_timestamp"]
                if source_timestamp is not None and datetime.fromisoformat(source_timestamp) > retrieved_dt:
                    raise ValueError("source_timestamp no puede ser posterior a retrieved_at.")
                # Schema v6+ permits distinct economic events at the same instant.
                # Only an identical event_identity may be idempotent. Do not use
                # INSERT OR IGNORE: it also masks CHECK violations.
                key = (
                    instrument_id, normalized["action_type"], effective_dt.isoformat(),
                    provider, retrieved,
                )
                if captured_by_athena:
                    # Only a previous locally captured event can establish
                    # idempotence across fetches. Legacy provider timestamps
                    # are NOT proof that ATHENA knew the event earlier.
                    already_captured = connection.execute(
                        """SELECT id FROM corporate_actions
                           WHERE instrument_id = ? AND action_type = ? AND effective_at = ?
                             AND source_provider = ? AND cash_amount IS ?
                             AND split_ratio IS ? AND currency IS ?
                             AND source_timestamp IS ? AND capture_verified = 1
                           LIMIT 1""",
                        (
                            instrument_id, normalized["action_type"], effective_dt.isoformat(),
                            provider, normalized["cash_amount"], normalized["split_ratio"],
                            normalized["currency"], source_timestamp,
                        ),
                    ).fetchone()
                    if already_captured is not None:
                        continue
                cursor = connection.execute(
                    """INSERT INTO corporate_actions (
                        instrument_id, action_type, effective_at, cash_amount,
                        split_ratio, currency, source_provider, source_timestamp, retrieved_at, capture_verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT DO NOTHING""",
                    (
                        instrument_id, normalized["action_type"], effective_dt.isoformat(),
                        normalized["cash_amount"], normalized["split_ratio"],
                        normalized["currency"], provider, source_timestamp, retrieved,
                        int(captured_by_athena),
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                    continue
                existing = connection.execute(
                    """SELECT source_timestamp FROM corporate_actions
                       WHERE instrument_id = ? AND action_type = ? AND effective_at = ?
                         AND source_provider = ? AND retrieved_at = ?
                         AND cash_amount IS ? AND split_ratio IS ? AND currency IS ?""",
                    (
                        *key, normalized["cash_amount"], normalized["split_ratio"],
                        normalized["currency"],
                    ),
                ).fetchone()
                if existing is None or existing["source_timestamp"] != source_timestamp:
                    # Same economic event and retrieval identity cannot silently
                    # change its declared source timestamp on replay.
                    raise ValueError(
                        "Corporate action PIT provenance conflict: source timestamp "
                        "changed for an immutable economic event."
                    )
        return CorporateActionSaveStats(received=len(buffered), inserted=inserted, unchanged=len(buffered)-inserted)

    def list_for_instrument(self, instrument_id: int, *, source_provider: str | None = None, knowledge_cutoff: datetime | None = None, effective_from: datetime | None = None, effective_to: datetime | None = None) -> list[dict[str, Any]]:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        self._initialize_schema()
        params: list[object] = [instrument_id]
        clauses = ["instrument_id = ?"]
        if source_provider is not None:
            clauses.append("source_provider = ?"); params.append(self._required_text(source_provider, "source_provider"))
        cutoff_iso: str | None = None
        if knowledge_cutoff is not None:
            cutoff_iso = self._utc_iso(knowledge_cutoff, "knowledge_cutoff")
            clauses.extend(("retrieved_at <= ?", "effective_at <= ?")); params.extend((cutoff_iso, cutoff_iso))
        self._append_effective_bounds(clauses, params, effective_from, effective_to)
        result = self._query(clauses, params)
        if cutoff_iso is not None:
            for row in result:
                if row["retrieved_at"] > cutoff_iso or row["effective_at"] > cutoff_iso:
                    raise RuntimeError("Una corporate action posterior al knowledge_cutoff atravesó el filtro PIT.")
        return result

    def list_known_future_for_instrument(self, instrument_id: int, *, knowledge_cutoff: datetime, source_provider: str | None = None, effective_to: datetime | None = None) -> list[dict[str, Any]]:
        """Actions ATHENA already knew at cutoff but whose economic date is future.

        This is intentionally separate from list_for_instrument so backtests cannot
        accidentally mix paid/effective history with declarations known in advance.
        """
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        self._initialize_schema()
        cutoff_iso = self._utc_iso(knowledge_cutoff, "knowledge_cutoff")
        params: list[object] = [instrument_id, cutoff_iso, cutoff_iso]
        clauses = ["instrument_id = ?", "retrieved_at <= ?", "effective_at > ?"]
        if source_provider is not None:
            clauses.append("source_provider = ?"); params.append(self._required_text(source_provider, "source_provider"))
        if effective_to is not None:
            clauses.append("effective_at <= ?"); params.append(self._utc_iso(effective_to, "effective_to"))
        result = self._query(clauses, params)
        for row in result:
            if row["retrieved_at"] > cutoff_iso or row["effective_at"] <= cutoff_iso:
                raise RuntimeError("Una corporate action violó la vista PIT de acciones futuras conocidas.")
        return result

    def _append_effective_bounds(self, clauses: list[str], params: list[object], effective_from: datetime | None, effective_to: datetime | None) -> None:
        if effective_from is not None:
            clauses.append("effective_at >= ?"); params.append(self._utc_iso(effective_from, "effective_from"))
        if effective_to is not None:
            clauses.append("effective_at <= ?"); params.append(self._utc_iso(effective_to, "effective_to"))
        if effective_from is not None and effective_to is not None and effective_from.astimezone(timezone.utc) > effective_to.astimezone(timezone.utc):
            raise ValueError("effective_from no puede ser posterior a effective_to.")

    def _query(self, clauses: list[str], params: list[object]) -> list[dict[str, Any]]:
        with self._database.connect() as connection:
            rows = connection.execute(f"SELECT * FROM corporate_actions WHERE {' AND '.join(clauses)} ORDER BY effective_at ASC, id ASC", tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def _initialize_schema(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS corporate_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, instrument_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL CHECK (action_type IN ('dividend', 'split')),
                    effective_at TEXT NOT NULL, cash_amount REAL, split_ratio REAL, currency TEXT,
                    source_provider TEXT NOT NULL, source_timestamp TEXT, retrieved_at TEXT NOT NULL, capture_verified INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (instrument_id) REFERENCES instruments(id) ON DELETE CASCADE,
                    CHECK ((action_type = 'dividend' AND cash_amount > 0 AND split_ratio IS NULL) OR (action_type = 'split' AND split_ratio > 0 AND cash_amount IS NULL)),
                    UNIQUE (instrument_id, action_type, effective_at, source_provider, retrieved_at));
                CREATE INDEX IF NOT EXISTS idx_corporate_actions_instrument_effective ON corporate_actions (instrument_id, effective_at);
                CREATE INDEX IF NOT EXISTS idx_corporate_actions_pit ON corporate_actions (instrument_id, retrieved_at, effective_at);
            """)
            # Existing databases must not gain historical capture authority.
            # Their pre-existing rows remain explicitly unverified.
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(corporate_actions)"
                ).fetchall()
            }
            if "capture_verified" not in columns:
                connection.execute(
                    "ALTER TABLE corporate_actions ADD COLUMN "
                    "capture_verified INTEGER NOT NULL DEFAULT 0"
                )

    def _normalize_action(self, value: dict[str, Any]) -> dict[str, Any]:
        action_type = self._required_text(value.get("action_type", value.get("type", "")), "action_type").lower()
        if action_type not in self._VALID_TYPES:
            raise ValueError("action_type debe ser dividend o split.")
        effective_at = self._parse_datetime(value.get("effective_at", value.get("effectiveAt")), "effective_at")
        source_raw = value.get("source_timestamp", value.get("sourceTimestamp"))
        source_timestamp = None if source_raw is None else self._parse_datetime(source_raw, "source_timestamp")
        cash_amount = self._optional_positive_number(value.get("cash_amount", value.get("cashAmount")), "cash_amount")
        split_ratio = self._optional_positive_number(value.get("split_ratio", value.get("splitRatio")), "split_ratio")
        if action_type == "dividend":
            if cash_amount is None or split_ratio is not None: raise ValueError("Un dividendo requiere cash_amount y no acepta split_ratio.")
        elif split_ratio is None or cash_amount is not None:
            raise ValueError("Un split requiere split_ratio y no acepta cash_amount.")
        currency_raw = value.get("currency"); currency = None
        if currency_raw is not None:
            currency = self._required_text(str(currency_raw), "currency").upper()
            if len(currency) != 3 or any(character < "A" or character > "Z" for character in currency):
                raise ValueError("currency debe ser un código ISO de tres letras ASCII.")
        return {"action_type": action_type, "effective_at": effective_at, "cash_amount": cash_amount, "split_ratio": split_ratio, "currency": currency, "source_timestamp": source_timestamp}

    def _parse_datetime(self, value: Any, field: str) -> str:
        if isinstance(value, datetime): return self._utc_iso(value, field)
        if isinstance(value, str):
            try: return self._utc_iso(datetime.fromisoformat(value), field)
            except ValueError as exc: raise ValueError(f"{field} no contiene una fecha ISO válida.") from exc
        raise ValueError(f"{field} es obligatorio.")

    def _required_text(self, value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized: raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _utc_iso(self, value: datetime, field: str) -> str:
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc).isoformat()

    def _optional_positive_number(self, value: Any, field: str) -> float | None:
        if value is None: return None
        if isinstance(value, bool): raise ValueError(f"{field} no acepta booleanos.")
        result = float(value)
        if not math.isfinite(result) or result <= 0: raise ValueError(f"{field} debe ser un número finito positivo.")
        return result
