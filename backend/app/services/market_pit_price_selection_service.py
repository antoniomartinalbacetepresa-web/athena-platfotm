"""Exact-instant PIT selection of persisted market prices for outcome evaluation.

SQLite julianday predicates are only a coarse indexable prefilter: their
millisecond precision cannot establish microsecond PIT eligibility. Python
checks the original offset-aware instants before selecting any observation.
This is retrospective evaluation, not evidence of model skill or authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import validated_market_source_provider


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} debe incluir zona horaria.")
    return value.astimezone(timezone.utc)


def _stored_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def select_pit_prices(
    database: AthenaDatabase, *,
    instrument_id: int,
    at_or_after: datetime,
    not_after: datetime,
    knowledge_cutoff: datetime,
) -> tuple[dict[str, Any], ...]:
    """Return one latest-knowable row per UTC instant, ordered by observation.

    Reject future retrieval, retrieval before the observation, non-finite
    prices, forbidden/untraceable providers, and invalid source timestamps.
    Never compare timestamp strings
    lexicographically: their timezone offsets may differ.
    """
    start = _utc(at_or_after, "at_or_after")
    end = _utc(not_after, "not_after")
    cutoff = _utc(knowledge_cutoff, "knowledge_cutoff")
    if end < start:
        return ()
    # The one-second SQL margin is deliberately larger than julianday's
    # rounding error. Exact boundaries are checked again in Python.
    sql = """
        SELECT id, observed_at, retrieved_at, source_timestamp, source_provider,
               COALESCE(close, adjusted_close) AS price
        FROM market_observations
        WHERE instrument_id = ?
          AND julianday(observed_at) >= julianday(?) - (1.0 / 86400.0)
          AND julianday(observed_at) <= julianday(?) + (1.0 / 86400.0)
          AND julianday(retrieved_at) <= julianday(?) + (1.0 / 86400.0)
          AND typeof(COALESCE(close, adjusted_close)) IN ('integer', 'real')
          AND COALESCE(close, adjusted_close) > 0
    """
    latest: dict[datetime, tuple[datetime, int, dict[str, Any]]] = {}
    with database.connect() as connection:
        for row in connection.execute(sql, (
            instrument_id, start.isoformat(), end.isoformat(), cutoff.isoformat(),
        )):
            observed = _stored_utc(row["observed_at"])
            retrieved = _stored_utc(row["retrieved_at"])
            if (
                observed is None or retrieved is None
                or not start <= observed <= end
                or not observed <= retrieved <= cutoff
            ):
                continue
            # The historical coverage and ingestion boundaries also reject
            # source evidence dated after retrieval. Enforce it here for both
            # outcomes and frozen benchmarks, including imported legacy rows.
            source_timestamp = row["source_timestamp"]
            if source_timestamp is not None:
                source_instant = _stored_utc(source_timestamp)
                if source_instant is None or source_instant > retrieved:
                    continue
            try:
                provider = validated_market_source_provider(row["source_provider"])
            except ValueError:
                continue
            price = float(row["price"])
            if not math.isfinite(price) or price <= 0:
                continue
            candidate = {
                "observed_at": str(row["observed_at"]),
                "retrieved_at": str(row["retrieved_at"]),
                "source_provider": provider,
                "price": price,
            }
            key = (retrieved, int(row["id"]))
            previous = latest.get(observed)
            if previous is None or key > (previous[0], previous[1]):
                latest[observed] = (retrieved, int(row["id"]), candidate)
    return tuple(latest[observed][2] for observed in sorted(latest))
