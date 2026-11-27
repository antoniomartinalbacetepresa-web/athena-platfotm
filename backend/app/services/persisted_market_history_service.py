"""Read local history without fetching providers or certifying source rights."""
from datetime import datetime, timedelta, timezone
import heapq
import math

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import validated_market_source_provider
from app.services.market_pit_price_selection_service import _stored_utc


class PersistedMarketHistoryService:
    def __init__(self, database: AthenaDatabase | None = None):
        self._database = database if database is not None else AthenaDatabase()

    def get_history(self, *, instrument_id: int, source_provider: str,
                    observed_from: datetime, observed_to: datetime,
                    as_of: datetime, limit: int = 400) -> dict:
        if type(instrument_id) is not int or instrument_id <= 0:
            raise ValueError("instrumentId debe ser positivo.")
        provider = validated_market_source_provider(source_provider)
        for value in (observed_from, observed_to, as_of):
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError("Las fechas deben incluir zona horaria.")
        start, end, cutoff = [value.astimezone(timezone.utc)
                              for value in (observed_from, observed_to, as_of)]
        if not start <= end <= cutoff or end - start > timedelta(days=366):
            raise ValueError("Intervalo inválido: máximo 366 días y hasta asOf.")
        if cutoff > datetime.now(timezone.utc):
            raise ValueError("asOf no puede estar en el futuro.")
        if type(limit) is not int or not 1 <= limit <= 400:
            raise ValueError("limit debe estar entre 1 y 400.")
        self._database.initialize()
        points = []
        with self._database.connect() as connection:
            # Catalogue identity and prices come from the same SQLite snapshot.
            connection.execute("BEGIN")
            listing = connection.execute(
                "SELECT * FROM instruments WHERE id = ?", (instrument_id,)
            ).fetchone()
            if listing is None:
                raise LookupError("Instrumento no encontrado.")
            rows = connection.execute(
                """SELECT * FROM market_observations
                   WHERE instrument_id = ? AND source_provider = ?
                     AND julianday(observed_at) >= julianday(?) - 1.0 / 86400
                     AND julianday(observed_at) <= julianday(?) + 1.0 / 86400
                     AND julianday(retrieved_at) <= julianday(?) + 1.0 / 86400
                   ORDER BY julianday(observed_at) DESC, id DESC""",
                (instrument_id, provider, start.isoformat(), end.isoformat(), cutoff.isoformat()),
            )
            for row in rows:
                observed = _stored_utc(row["observed_at"])
                retrieved = _stored_utc(row["retrieved_at"])
                source = _stored_utc(row["source_timestamp"])
                if (observed is None or retrieved is None
                        or not start <= observed <= end
                        or not observed <= retrieved <= cutoff
                        or (row["source_timestamp"] is not None
                            and (source is None or source > retrieved))):
                    continue
                numbers = {name: row[name] for name in
                           ("open", "high", "low", "close", "adjusted_close", "volume")}
                if numbers["close"] is None or any(
                    value is not None and (not isinstance(value, (int, float))
                                           or not math.isfinite(value)
                                           or (value < 0 if name == "volume" else value <= 0))
                    for name, value in numbers.items()
                ):
                    continue
                low, high = numbers["low"], numbers["high"]
                if ((low is not None and high is not None and low > high)
                        or any(value is not None and (
                            (low is not None and value < low)
                            or (high is not None and value > high))
                            for value in (numbers["open"], numbers["close"]))):
                    continue
                point = {
                    "observationId": row["id"], "instrumentId": instrument_id,
                    "symbol": listing["symbol"], "currency": listing["currency"],
                    "exchange": listing["exchange_short_name"],
                    "canonicalIdentityStatus": "matched_internal_listing",
                    "timestamp": observed.isoformat(), "retrievedAt": retrieved.isoformat(),
                    "availableAt": retrieved.isoformat(),
                    "sourceTimestamp": source.isoformat() if source else None,
                    "sourceProvider": provider,
                    **{name: numbers[name] for name in ("open", "high", "low", "close", "volume")},
                    "adjustedClose": numbers["adjusted_close"],
                    "historicalPointInTimeEligible": False, "realTimePriceVerified": False,
                }
                # Keep bounded output while selecting by exact UTC instants;
                # SQLite julianday ordering loses sub-millisecond precision.
                candidate = (observed, row["id"], point)
                if len(points) <= limit:
                    heapq.heappush(points, candidate)
                elif candidate[:2] > points[0][:2]:
                    heapq.heapreplace(points, candidate)
        truncated = len(points) > limit
        selected = sorted(points, key=lambda item: item[:2])[-limit:]
        return {"data": [item[2] for item in selected], "provenance": {
            "retrievalMode": "persisted_local_history", "asOf": cutoff.isoformat(),
            "instrumentId": instrument_id, "sourceProvider": provider,
            "observedFrom": start.isoformat(), "observedTo": end.isoformat(),
            "limit": limit, "truncated": truncated,
            "historyStatus": "persisted_unverified" if points else "empty",
            "availabilityBasis": "local_retrieval_not_historical_publication",
            "listingIdentityBasis": "current_catalogue_not_historical_identity",
            "licenceVerified": False, "historicalPointInTimeEligible": False,
            "productionCoverageClaimed": False, "researchOnly": True,
            "orderExecutionAllowed": False,
        }}
