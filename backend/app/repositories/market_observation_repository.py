from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable

from app.database.athena_database import AthenaDatabase


@dataclass(frozen=True)
class MarketObservationSaveStats:
    received: int
    inserted: int
    unchanged: int


class MarketObservationRepository:
    """Persists immutable point-in-time market observations."""

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def save_many(
        self,
        *,
        instrument_id: int,
        observations: Iterable[dict[str, Any]],
        source_provider: str,
        retrieved_at: datetime,
    ) -> MarketObservationSaveStats:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")

        provider = self._required_text(source_provider, "source_provider")
        retrieved = self._utc_iso(retrieved_at, "retrieved_at")
        retrieved_dt = datetime.fromisoformat(retrieved)
        buffered = list(observations)

        self._database.initialize()

        inserted = 0
        with self._database.connect() as connection:
            for observation in buffered:
                normalized = self._normalize_observation(observation)
                observed_dt = datetime.fromisoformat(normalized["observed_at"])
                if retrieved_dt < observed_dt:
                    raise ValueError(
                        "retrieved_at no puede ser anterior a observed_at."
                    )
                source_timestamp = normalized["source_timestamp"]
                if source_timestamp is not None:
                    source_dt = datetime.fromisoformat(source_timestamp)
                    if source_dt > retrieved_dt:
                        raise ValueError(
                            "source_timestamp no puede ser posterior a retrieved_at."
                        )

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO market_observations (
                        instrument_id,
                        observed_at,
                        open,
                        high,
                        low,
                        close,
                        adjusted_close,
                        volume,
                        market_cap_usd,
                        source_provider,
                        source_timestamp,
                        retrieved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instrument_id,
                        normalized["observed_at"],
                        normalized["open"],
                        normalized["high"],
                        normalized["low"],
                        normalized["close"],
                        normalized["adjusted_close"],
                        normalized["volume"],
                        normalized["market_cap_usd"],
                        provider,
                        normalized["source_timestamp"],
                        retrieved,
                    ),
                )
                if cursor.rowcount == 1:
                    inserted += 1

        return MarketObservationSaveStats(
            received=len(buffered),
            inserted=inserted,
            unchanged=len(buffered) - inserted,
        )

    def list_for_instrument(
        self,
        instrument_id: int,
        *,
        source_provider: str | None = None,
        knowledge_cutoff: datetime | None = None,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")
        self._database.initialize()

        params: list[object] = [instrument_id]
        clauses: list[str] = ["instrument_id = ?"]

        if source_provider is not None:
            provider = self._required_text(source_provider, "source_provider")
            clauses.append("source_provider = ?")
            params.append(provider)

        cutoff_iso: str | None = None
        if knowledge_cutoff is not None:
            cutoff_iso = self._utc_iso(knowledge_cutoff, "knowledge_cutoff")
            clauses.append("retrieved_at <= ?")
            params.append(cutoff_iso)
            clauses.append("observed_at <= ?")
            params.append(cutoff_iso)

        if observed_from is not None:
            observed_from_iso = self._utc_iso(observed_from, "observed_from")
            clauses.append("observed_at >= ?")
            params.append(observed_from_iso)

        if observed_to is not None:
            observed_to_iso = self._utc_iso(observed_to, "observed_to")
            clauses.append("observed_at <= ?")
            params.append(observed_to_iso)

        if observed_from is not None and observed_to is not None:
            if observed_from.astimezone(timezone.utc) > observed_to.astimezone(timezone.utc):
                raise ValueError("observed_from no puede ser posterior a observed_to.")

        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM market_observations
                WHERE {' AND '.join(clauses)}
                ORDER BY observed_at ASC, id ASC
                """,
                tuple(params),
            ).fetchall()

        result = [dict(row) for row in rows]
        if cutoff_iso is not None:
            for row in result:
                if row["retrieved_at"] > cutoff_iso or row["observed_at"] > cutoff_iso:
                    raise StateError(
                        "Una observación posterior al knowledge_cutoff atravesó el filtro PIT."
                    )
        return result

    def _normalize_observation(self, value: dict[str, Any]) -> dict[str, Any]:
        observed_at_raw = value.get("observed_at", value.get("timestamp"))
        if isinstance(observed_at_raw, datetime):
            observed_at = self._utc_iso(observed_at_raw, "observed_at")
        elif isinstance(observed_at_raw, str):
            try:
                parsed = datetime.fromisoformat(observed_at_raw)
            except ValueError as exc:
                raise ValueError("observed_at no contiene una fecha ISO válida.") from exc
            observed_at = self._utc_iso(parsed, "observed_at")
        else:
            raise ValueError("observed_at es obligatorio.")

        source_timestamp_raw = value.get("source_timestamp")
        source_timestamp = None
        if source_timestamp_raw is not None:
            if isinstance(source_timestamp_raw, datetime):
                source_timestamp = self._utc_iso(
                    source_timestamp_raw,
                    "source_timestamp",
                )
            elif isinstance(source_timestamp_raw, str):
                try:
                    parsed_source = datetime.fromisoformat(source_timestamp_raw)
                except ValueError as exc:
                    raise ValueError(
                        "source_timestamp no contiene una fecha ISO válida."
                    ) from exc
                source_timestamp = self._utc_iso(
                    parsed_source,
                    "source_timestamp",
                )
            else:
                raise ValueError("source_timestamp debe ser una fecha válida.")

        return {
            "observed_at": observed_at,
            "open": self._optional_number(value.get("open")),
            "high": self._optional_number(value.get("high")),
            "low": self._optional_number(value.get("low")),
            "close": self._optional_positive_number(value.get("close"), "close"),
            "adjusted_close": self._optional_positive_number(
                value.get("adjusted_close", value.get("adjustedClose")),
                "adjusted_close",
            ),
            "volume": self._optional_non_negative_number(value.get("volume"), "volume"),
            "market_cap_usd": self._optional_positive_number(
                value.get("market_cap_usd", value.get("marketCapUsd")),
                "market_cap_usd",
            ),
            "source_timestamp": source_timestamp,
        }

    def _required_text(self, value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _utc_iso(self, value: datetime, field: str) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc).isoformat()

    def _optional_number(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("Los campos numéricos no aceptan booleanos.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Los campos numéricos deben ser finitos.")
        return result

    def _optional_positive_number(self, value: Any, field: str) -> float | None:
        result = self._optional_number(value)
        if result is not None and result <= 0:
            raise ValueError(f"{field} debe ser positivo cuando está presente.")
        return result

    def _optional_non_negative_number(self, value: Any, field: str) -> float | None:
        result = self._optional_number(value)
        if result is not None and result < 0:
            raise ValueError(f"{field} no puede ser negativo.")
        return result
