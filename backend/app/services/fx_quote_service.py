from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Protocol

from app.services.yahoo_market_service import YahooMarketService


class _MarketQuoteService(Protocol):
    def get_quote(self, symbol: str) -> dict[str, Any] | None: ...


class FxQuoteService:
    """Resolve current FX conversion rates with explicit provenance.

    The service deliberately exposes only a *current* conversion contract. It
    does not pretend that a rate retrieved now was known at an earlier point in
    time. Historical portfolio/recommendation evaluation must use a separately
    persisted PIT FX observation before it can be considered valid.
    """

    def __init__(self, *, market_service: _MarketQuoteService | None = None) -> None:
        self._market_service = market_service or YahooMarketService()

    def get_current_rate(self, *, base_currency: str, quote_currency: str) -> dict[str, Any]:
        base = self._currency(base_currency, "base_currency")
        quote = self._currency(quote_currency, "quote_currency")

        if base == quote:
            now = datetime.now(timezone.utc).isoformat()
            return {
                "status": "fx_identity",
                "baseCurrency": base,
                "quoteCurrency": quote,
                "rate": 1.0,
                "observedAt": now,
                "retrievedAt": now,
                "sourceProvider": "identity",
                "sourceSymbol": None,
                "historicalPointInTimeEligible": False,
            }

        source_symbol = f"{base}{quote}=X"
        payload = self._market_service.get_quote(source_symbol)
        if not isinstance(payload, dict):
            raise RuntimeError("La fuente FX no devolvió una cotización verificable.")

        returned_symbol = str(payload.get("symbol") or "").strip().upper()
        if returned_symbol != source_symbol:
            raise RuntimeError("La fuente FX devolvió un instrumento distinto al solicitado.")

        try:
            rate = float(payload.get("close"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("La cotización FX no contiene una tasa numérica válida.") from exc
        if not isfinite(rate) or rate <= 0:
            raise RuntimeError("La cotización FX no contiene una tasa positiva y finita.")

        source_provider = str(payload.get("sourceProvider") or "").strip()
        if not source_provider:
            raise RuntimeError("La cotización FX no contiene proveedor de procedencia.")

        observed_at = self._aware_iso(payload.get("timestamp"), "timestamp")
        retrieved_at = self._aware_iso(payload.get("retrievedAt"), "retrievedAt")
        if retrieved_at < observed_at:
            raise RuntimeError("La recuperación FX no puede preceder a su observación.")

        returned_currency = str(payload.get("currency") or "").strip().upper()
        if returned_currency and returned_currency != quote:
            raise RuntimeError("La moneda de cotización FX no coincide con la moneda destino.")

        return {
            "status": "fx_current_ready",
            "baseCurrency": base,
            "quoteCurrency": quote,
            "rate": rate,
            "observedAt": observed_at.isoformat(),
            "retrievedAt": retrieved_at.isoformat(),
            "sourceProvider": source_provider,
            "sourceSymbol": source_symbol,
            "historicalPointInTimeEligible": False,
            "policy": {
                "currentConversionOnly": True,
                "historicalBackdatingForbidden": True,
                "portfolioHistoricalEvaluationRequiresPersistedPitFx": True,
            },
        }

    def _currency(self, value: str, field: str) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError(f"{field} debe ser un código ISO de tres letras.")
        return normalized

    def _aware_iso(self, value: object, field: str) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise RuntimeError(f"La cotización FX no contiene {field}.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"La cotización FX contiene {field} inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"La cotización FX contiene {field} sin zona horaria.")
        return parsed.astimezone(timezone.utc)
