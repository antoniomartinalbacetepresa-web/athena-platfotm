from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from app.database.athena_database import AthenaDatabase


class RecommendationPortfolioEventJournalRepository:
    """Append-only, hash-chained journal for portfolio external cash-flow events."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def initialize(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS athena_recommendation_portfolio_event_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    event_type TEXT NOT NULL
                        CHECK (event_type = 'external_cash_flow'),
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    previous_record_fingerprint TEXT,
                    payload_fingerprint TEXT NOT NULL,
                    record_fingerprint TEXT NOT NULL UNIQUE,
                    persisted_at TEXT NOT NULL,
                    UNIQUE (tenant_id, portfolio_id, event_key),
                    UNIQUE (tenant_id, portfolio_id, source, source_ref)
                );

                CREATE INDEX IF NOT EXISTS idx_portfolio_event_journal_stream
                ON athena_recommendation_portfolio_event_journal(
                    tenant_id, portfolio_id, id
                );

                CREATE TABLE IF NOT EXISTS athena_recommendation_portfolio_event_journal_head (
                    tenant_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    event_count INTEGER NOT NULL CHECK (event_count >= 0),
                    head_record_fingerprint TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, portfolio_id)
                );
                """
            )

    def append_external_cash_flow(
        self,
        *,
        tenant_id: str,
        portfolio_id: str,
        event_key: str,
        amount: float,
        currency: str,
        occurred_at: datetime,
        available_at: datetime,
        source: str,
        source_ref: str,
    ) -> dict[str, Any]:
        self.initialize()
        tenant = self._text(tenant_id, "tenant_id")
        portfolio = self._text(portfolio_id, "portfolio_id")
        key = self._sha256(event_key, "event_key")
        numeric_amount = self._finite(amount, "amount")
        if abs(numeric_amount) <= 1e-12:
            raise ValueError("external cash-flow amount must be non-zero")
        event_currency = self._currency(currency, "currency")
        occurred = self._aware_utc(occurred_at, "occurred_at")
        available = self._aware_utc(available_at, "available_at")
        if occurred > available:
            raise ValueError("external cash flow violates occurred_at <= available_at")
        event_source = self._text(source, "source")
        event_source_ref = self._text(source_ref, "source_ref")

        payload = {
            "tenantId": tenant,
            "portfolioId": portfolio,
            "eventKey": key,
            "eventType": "external_cash_flow",
            "amount": numeric_amount,
            "currency": event_currency,
            "occurredAt": occurred.isoformat(),
            "availableAt": available.isoformat(),
            "source": event_source,
            "sourceRef": event_source_ref,
        }
        payload_fingerprint = self._fingerprint(payload)

        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_event_journal
                WHERE tenant_id = ? AND portfolio_id = ?
                ORDER BY id ASC
                """,
                (tenant, portfolio),
            ).fetchall()
            records = tuple(self._row(row) for row in rows)
            self._validate_chain(
                tenant_id=tenant,
                portfolio_id=portfolio,
                records=records,
                connection=connection,
            )

            for record in records:
                if record["event_key"] == key:
                    if record["payload_fingerprint"] != payload_fingerprint:
                        raise ValueError("event_key collision with different persisted payload")
                    return record
                if record["source"] == event_source and record["source_ref"] == event_source_ref:
                    raise ValueError("source provenance already identifies a different persisted event")

            previous = records[-1]["record_fingerprint"] if records else None
            persisted_at = datetime.now(timezone.utc).isoformat()
            record_core = {
                "payload": payload,
                "previousRecordFingerprint": previous,
                "persistedAt": persisted_at,
            }
            record_fingerprint = self._fingerprint(record_core)
            connection.execute(
                """
                INSERT INTO athena_recommendation_portfolio_event_journal (
                    tenant_id, portfolio_id, event_key, event_type, amount, currency,
                    occurred_at, available_at, source, source_ref,
                    previous_record_fingerprint, payload_fingerprint,
                    record_fingerprint, persisted_at
                ) VALUES (?, ?, ?, 'external_cash_flow', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    portfolio,
                    key,
                    numeric_amount,
                    event_currency,
                    occurred.isoformat(),
                    available.isoformat(),
                    event_source,
                    event_source_ref,
                    previous,
                    payload_fingerprint,
                    record_fingerprint,
                    persisted_at,
                ),
            )
            new_count = len(records) + 1
            connection.execute(
                """
                INSERT INTO athena_recommendation_portfolio_event_journal_head (
                    tenant_id, portfolio_id, event_count, head_record_fingerprint, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, portfolio_id)
                DO UPDATE SET
                    event_count = excluded.event_count,
                    head_record_fingerprint = excluded.head_record_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (tenant, portfolio, new_count, record_fingerprint, persisted_at),
            )
            row = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_event_journal
                WHERE tenant_id = ? AND portfolio_id = ? AND event_key = ?
                """,
                (tenant, portfolio, key),
            ).fetchone()
        if row is None:
            raise RuntimeError("persisted portfolio event could not be reloaded")
        return self._row(row)

    def scan_external_cash_flows(
        self,
        *,
        tenant_id: str,
        portfolio_id: str,
        period_start: datetime,
        period_end: datetime,
        as_of: datetime,
    ) -> tuple[dict[str, Any], ...]:
        self.initialize()
        tenant = self._text(tenant_id, "tenant_id")
        portfolio = self._text(portfolio_id, "portfolio_id")
        start = self._aware_utc(period_start, "period_start")
        end = self._aware_utc(period_end, "period_end")
        cutoff = self._aware_utc(as_of, "as_of")
        if not start < end <= cutoff:
            raise ValueError("journal scan requires period_start < period_end <= as_of")

        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM athena_recommendation_portfolio_event_journal
                WHERE tenant_id = ? AND portfolio_id = ?
                ORDER BY id ASC
                """,
                (tenant, portfolio),
            ).fetchall()
            records = tuple(self._row(row) for row in rows)
            self._validate_chain(
                tenant_id=tenant,
                portfolio_id=portfolio,
                records=records,
                connection=connection,
            )

        selected: list[dict[str, Any]] = []
        for record in records:
            occurred = self._aware_iso(record["occurred_at"], "occurred_at")
            available = self._aware_iso(record["available_at"], "available_at")
            if available > cutoff:
                continue
            if start < occurred < end:
                selected.append(record)
        return tuple(selected)

    def _validate_chain(
        self,
        *,
        tenant_id: str,
        portfolio_id: str,
        records: tuple[dict[str, Any], ...],
        connection: Any,
    ) -> None:
        previous: str | None = None
        for record in records:
            if record["tenant_id"] != tenant_id or record["portfolio_id"] != portfolio_id:
                raise ValueError("portfolio journal stream identity mismatch")
            if record["previous_record_fingerprint"] != previous:
                raise ValueError("portfolio journal hash chain is broken")
            payload = self._payload(record)
            if self._fingerprint(payload) != record["payload_fingerprint"]:
                raise ValueError("portfolio journal payload was modified")
            record_core = {
                "payload": payload,
                "previousRecordFingerprint": previous,
                "persistedAt": record["persisted_at"],
            }
            if self._fingerprint(record_core) != record["record_fingerprint"]:
                raise ValueError("portfolio journal record was modified")
            previous = record["record_fingerprint"]

        head = connection.execute(
            """
            SELECT event_count, head_record_fingerprint
            FROM athena_recommendation_portfolio_event_journal_head
            WHERE tenant_id = ? AND portfolio_id = ?
            """,
            (tenant_id, portfolio_id),
        ).fetchone()
        if not records:
            if head is not None and (
                int(head["event_count"]) != 0 or head["head_record_fingerprint"] is not None
            ):
                raise ValueError("portfolio journal head does not reconcile to empty stream")
            return
        if head is None:
            raise ValueError("portfolio journal head is missing")
        if int(head["event_count"]) != len(records):
            raise ValueError("portfolio journal event count does not reconcile")
        if str(head["head_record_fingerprint"]) != previous:
            raise ValueError("portfolio journal head fingerprint does not reconcile")

    def _row(self, row: Any) -> dict[str, Any]:
        record = {
            "id": int(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "portfolio_id": str(row["portfolio_id"]),
            "event_key": str(row["event_key"]),
            "event_type": str(row["event_type"]),
            "amount": self._finite(row["amount"], "persisted amount"),
            "currency": str(row["currency"]),
            "occurred_at": str(row["occurred_at"]),
            "available_at": str(row["available_at"]),
            "source": str(row["source"]),
            "source_ref": str(row["source_ref"]),
            "previous_record_fingerprint": (
                None
                if row["previous_record_fingerprint"] is None
                else str(row["previous_record_fingerprint"])
            ),
            "payload_fingerprint": str(row["payload_fingerprint"]),
            "record_fingerprint": str(row["record_fingerprint"]),
            "persisted_at": str(row["persisted_at"]),
        }
        self._sha256(record["event_key"], "persisted event_key")
        self._sha256(record["payload_fingerprint"], "persisted payload_fingerprint")
        self._sha256(record["record_fingerprint"], "persisted record_fingerprint")
        if record["previous_record_fingerprint"] is not None:
            self._sha256(
                record["previous_record_fingerprint"],
                "persisted previous_record_fingerprint",
            )
        self._currency(record["currency"], "persisted currency")
        self._aware_iso(record["occurred_at"], "persisted occurred_at")
        self._aware_iso(record["available_at"], "persisted available_at")
        self._aware_iso(record["persisted_at"], "persisted persisted_at")
        if record["event_type"] != "external_cash_flow":
            raise ValueError("unsupported persisted portfolio event type")
        return record

    @staticmethod
    def _payload(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "tenantId": record["tenant_id"],
            "portfolioId": record["portfolio_id"],
            "eventKey": record["event_key"],
            "eventType": record["event_type"],
            "amount": record["amount"],
            "currency": record["currency"],
            "occurredAt": record["occurred_at"],
            "availableAt": record["available_at"],
            "source": record["source"],
            "sourceRef": record["source_ref"],
        }

    @staticmethod
    def _serialize(value: object) -> str:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("portfolio journal contains non-serializable/non-finite data") from exc

    @classmethod
    def _fingerprint(cls, payload: object) -> str:
        return hashlib.sha256(cls._serialize(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text

    @classmethod
    def _currency(cls, value: object, field: str) -> str:
        currency = cls._text(value, field).upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError(f"{field} must be a three-letter currency code")
        return currency

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError(f"{field} must be a SHA-256 hexadecimal fingerprint")
        return text

    @staticmethod
    def _finite(value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} must be finite")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be finite") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        return numeric

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include timezone")
        return value.astimezone(timezone.utc)

    @classmethod
    def _aware_iso(cls, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be ISO datetime with timezone")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be valid ISO datetime") from exc
        return cls._aware_utc(parsed, field)
