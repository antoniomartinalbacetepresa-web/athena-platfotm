"""Fail-closed provenance checks for a pilot market observation.

This module does not fetch data, grant redistribution rights, or verify a provider.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class UnverifiedMarketObservation(ValueError):
    """Observation cannot be used as verified research evidence."""


def validate_pilot_observation(observation: dict, *, as_of: datetime) -> dict:
    """Validate a closed daily bar without fabricating missing provenance.

    The caller must separately establish the legal basis of the provider licence.
    """
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise UnverifiedMarketObservation("as_of must be a timezone-aware datetime")
    required = (
        "instrument_id", "symbol", "source", "license_reference",
        "observation_at", "available_at", "retrieved_at", "currency",
        "close", "volume", "adjustment_status",
    )
    if not isinstance(observation, dict) or any(
        not isinstance(observation.get(key), str) or not observation[key].strip()
        for key in required if key not in ("close", "volume", "currency")
    ) or any(key not in observation for key in required):
        raise UnverifiedMarketObservation("missing mandatory provenance or financial fields")
    # Provider metadata is displayed and audited; reject embedded control characters.
    for key in ("instrument_id", "symbol", "source", "license_reference", "adjustment_status"):
        value = observation[key]
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise UnverifiedMarketObservation(f"invalid control character in {key}")
    currency = observation["currency"]
    if (not isinstance(currency, str) or len(currency) != 3 or
            not currency.isascii() or not currency.isalpha() or currency != currency.upper()):
        raise UnverifiedMarketObservation("currency must be an uppercase ISO 4217 code")
    timestamps = {}
    for key in ("observation_at", "available_at", "retrieved_at"):
        try:
            value = datetime.fromisoformat(observation[key].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise UnverifiedMarketObservation(f"invalid {key}") from exc
        if value.tzinfo is None:
            raise UnverifiedMarketObservation(f"{key} must include timezone")
        timestamps[key] = value.astimezone(timezone.utc)
    if not (timestamps["observation_at"] <= timestamps["available_at"] <=
            timestamps["retrieved_at"] <= as_of.astimezone(timezone.utc)):
        raise UnverifiedMarketObservation("future or inconsistent PIT timestamps")
    if isinstance(observation["close"], bool) or isinstance(observation["volume"], bool):
        raise UnverifiedMarketObservation("boolean close or volume is not financial evidence")
    try:
        close = Decimal(str(observation["close"]))
        volume = Decimal(str(observation["volume"]))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise UnverifiedMarketObservation("invalid close or volume") from exc
    if not close.is_finite() or close <= 0 or not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
        raise UnverifiedMarketObservation("nonfinite, fractional or out-of-range close/volume")
    if observation.get("bar_status") != "closed":
        raise UnverifiedMarketObservation("unclosed or unverified bar")
    if observation.get("license_verified") is not True:
        raise UnverifiedMarketObservation("provider license not independently verified")
    if observation.get("adjustment_status") not in ("raw", "split_adjusted", "total_return"):
        raise UnverifiedMarketObservation("unknown corporate-action adjustment")
    return dict(observation)
