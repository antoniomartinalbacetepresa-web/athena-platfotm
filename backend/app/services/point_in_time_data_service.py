from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.normalized_data import DataProvenance, NormalizedDatum


@dataclass(frozen=True)
class PointInTimeAvailability:
    available: bool
    reason: str
    as_of: str
    available_at: str | None

    def to_api_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "reason": self.reason,
            "asOf": self.as_of,
            "availableAt": self.available_at,
            "policy": "explicit_available_at_only",
        }


class PointInTimeDataService:
    """Prevents look-ahead by requiring an explicit knowledge-availability time."""

    def evaluate(
        self,
        provenance: DataProvenance,
        *,
        as_of: str,
    ) -> PointInTimeAvailability:
        as_of_dt = self._parse_timestamp(as_of, field_name="as_of")
        available_at = str(provenance.available_at or "").strip()
        if not available_at:
            return PointInTimeAvailability(
                available=False,
                reason="explicit_availability_timestamp_required",
                as_of=as_of_dt.isoformat(),
                available_at=None,
            )

        available_dt = self._parse_timestamp(
            available_at,
            field_name="available_at",
        )
        is_available = available_dt <= as_of_dt
        return PointInTimeAvailability(
            available=is_available,
            reason=(
                "available_at_or_before_as_of"
                if is_available
                else "available_after_as_of"
            ),
            as_of=as_of_dt.isoformat(),
            available_at=available_dt.isoformat(),
        )

    def filter_available(
        self,
        data: list[NormalizedDatum],
        *,
        as_of: str,
    ) -> list[NormalizedDatum]:
        return [
            datum
            for datum in data
            if self.evaluate(datum.provenance, as_of=as_of).available
        ]

    def _parse_timestamp(self, value: str, *, field_name: str) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} is required.")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field_name} must include a timezone offset.")
        return parsed.astimezone(timezone.utc)
