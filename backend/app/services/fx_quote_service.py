from __future__ import annotations

from datetime import date, datetime, time, timezone
from math import isfinite
from typing import Any, Protocol

from app.repositories.fx_rate_repository import FxRateRecord, FxRateRepository
from app.services.yahoo_market_service import YahooMarketService


class _MarketQuoteService(Protocol):
    def get_quote(self, symbol: str) -> dict[str, Any] | None: ...

    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]: ...


class FxQuoteService:
    """Resolve FX conversion rates with explicit provenance and PIT guards.

    Current quotes are never backdated. Historical observations can be persisted
    and replayed only when their original observation and retrieval timestamps
    were already knowable at the requested cutoff. When no repository is
    injected, the service retains its stateless behaviour for isolated callers.
    """

    def __init__(
        self,
        *,
        market_service: _MarketQuoteService | None = None,
        repository: FxRateRepository | None = None,
    ) -> None:
        self._market_service = market_service or YahooMarketService()
        self._repository = repository

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

        rate = self._positive_finite_rate(payload.get("close"))

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

    def get_historical_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        observed_on: date,
        knowledge_cutoff: datetime | None = None,
    ) -> dict[str, Any]:
        """Resolve or replay the FX close observed on a specific date.

        A historical evaluation must provide its original ``knowledge_cutoff``.
        If an immutable persisted observation existed by that cutoff it is
        replayed without contacting the upstream provider. Otherwise a new
        upstream retrieval is accepted only when its retrieval timestamp does
        not exceed the cutoff, then persisted when a repository is configured.
        """

        base = self._currency(base_currency, "base_currency")
        quote = self._currency(quote_currency, "quote_currency")
        target_date = self._date(observed_on, "observed_on")
        explicit_cutoff = knowledge_cutoff is not None
        cutoff = (
            self._aware_datetime(knowledge_cutoff, "knowledge_cutoff")
            if explicit_cutoff
            else None
        )
        target_observed_at = datetime.combine(
            target_date,
            time.min,
            tzinfo=timezone.utc,
        )
        if cutoff is not None and target_observed_at > cutoff:
            raise RuntimeError(
                "La fecha FX solicitada es posterior al corte de conocimiento; usarla introduciría lookahead."
            )

        if base == quote:
            retrieved_at = datetime.now(timezone.utc)
            effective_cutoff = cutoff or retrieved_at
            return {
                "status": "fx_historical_identity",
                "baseCurrency": base,
                "quoteCurrency": quote,
                "rate": 1.0,
                "observedOn": target_date.isoformat(),
                "observedAt": target_observed_at.isoformat(),
                "retrievedAt": retrieved_at.isoformat(),
                "knowledgeCutoff": effective_cutoff.isoformat(),
                "sourceProvider": "identity",
                "sourceSymbol": None,
                "historicalPointInTimeEligible": True,
                "replayedFromPersistence": False,
                "policy": {
                    "exactObservationDateRequired": True,
                    "retrievalMustNotExceedKnowledgeCutoff": True,
                    "identityConversionRequiresNoMarketObservation": True,
                },
            }

        source_symbol = f"{base}{quote}=X"
        replay_cutoff = cutoff or datetime.now(timezone.utc)
        if self._repository is not None:
            persisted = self._repository.get_pit(
                observed_on=target_date,
                base_currency=base,
                quote_currency=quote,
                source_symbol=source_symbol,
                knowledge_cutoff=replay_cutoff,
            )
            if persisted is not None:
                return self._persisted_payload(
                    record=persisted,
                    knowledge_cutoff=replay_cutoff,
                )

        rows = self._market_service.get_history(
            source_symbol,
            from_date=target_date.isoformat(),
            to_date=target_date.isoformat(),
        )
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("No existe una observación FX verificable para la fecha solicitada.")
        if len(rows) != 1 or not isinstance(rows[0], dict):
            raise RuntimeError("La fuente FX devolvió una observación histórica ambigua.")

        payload = rows[0]
        returned_symbol = str(payload.get("symbol") or "").strip().upper()
        if returned_symbol != source_symbol:
            raise RuntimeError("La fuente FX histórica devolvió un instrumento distinto al solicitado.")

        rate = self._positive_finite_rate(payload.get("close"))
        source_provider = str(payload.get("sourceProvider") or "").strip()
        if not source_provider:
            raise RuntimeError("La cotización FX histórica no contiene proveedor de procedencia.")

        observed_at = self._aware_iso(payload.get("timestamp"), "timestamp")
        retrieved_at = self._aware_iso(payload.get("retrievedAt"), "retrievedAt")
        if retrieved_at < observed_at:
            raise RuntimeError("La recuperación FX histórica no puede preceder a su observación.")
        if observed_at.date() != target_date:
            raise RuntimeError("La observación FX histórica no corresponde a la fecha solicitada.")

        effective_cutoff = cutoff or datetime.now(timezone.utc)
        if observed_at > effective_cutoff or retrieved_at > effective_cutoff:
            raise RuntimeError(
                "La observación FX fue conocida después del corte de conocimiento; usarla introduciría lookahead."
            )

        if self._repository is not None:
            self._repository.save(
                observed_on=target_date,
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                source_provider=source_provider,
                source_symbol=source_symbol,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
            )

        return self._historical_payload(
            base=base,
            quote=quote,
            rate=rate,
            target_date=target_date,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            knowledge_cutoff=effective_cutoff,
            source_provider=source_provider,
            source_symbol=source_symbol,
            replayed=False,
        )

    def _persisted_payload(
        self,
        *,
        record: FxRateRecord,
        knowledge_cutoff: datetime,
    ) -> dict[str, Any]:
        if record.source_symbol is None:
            raise RuntimeError("La observación FX persistida carece de símbolo de procedencia.")
        if record.observed_at > knowledge_cutoff or record.retrieved_at > knowledge_cutoff:
            raise RuntimeError("La observación FX persistida viola el corte PIT solicitado.")
        return self._historical_payload(
            base=record.base_currency,
            quote=record.quote_currency,
            rate=record.rate,
            target_date=record.observed_on,
            observed_at=record.observed_at,
            retrieved_at=record.retrieved_at,
            knowledge_cutoff=knowledge_cutoff,
            source_provider=record.source_provider,
            source_symbol=record.source_symbol,
            replayed=True,
        )

    def _historical_payload(
        self,
        *,
        base: str,
        quote: str,
        rate: float,
        target_date: date,
        observed_at: datetime,
        retrieved_at: datetime,
        knowledge_cutoff: datetime,
        source_provider: str,
        source_symbol: str,
        replayed: bool,
    ) -> dict[str, Any]:
        return {
            "status": "fx_historical_ready",
            "baseCurrency": base,
            "quoteCurrency": quote,
            "rate": rate,
            "observedOn": target_date.isoformat(),
            "observedAt": observed_at.isoformat(),
            "retrievedAt": retrieved_at.isoformat(),
            "knowledgeCutoff": knowledge_cutoff.isoformat(),
            "sourceProvider": source_provider,
            "sourceSymbol": source_symbol,
            "historicalPointInTimeEligible": True,
            "replayedFromPersistence": replayed,
            "policy": {
                "exactObservationDateRequired": True,
                "retrievalMustNotExceedKnowledgeCutoff": True,
                "historicalBackdatingForbidden": True,
                "persistObservationForFutureReplay": True,
                "persistedReplayRequiresOriginalRetrievalBeforeCutoff": True,
            },
        }

    def _currency(self, value: str, field: str) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError(f"{field} debe ser un código ISO de tres letras.")
        return normalized

    def _date(self, value: object, field: str) -> date:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise ValueError(f"{field} debe ser una fecha sin hora.")
        return value

    def _positive_finite_rate(self, value: object) -> float:
        if isinstance(value, bool):
            raise RuntimeError("La cotización FX no contiene una tasa numérica válida.")
        try:
            rate = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("La cotización FX no contiene una tasa numérica válida.") from exc
        if not isfinite(rate) or rate <= 0:
            raise RuntimeError("La cotización FX no contiene una tasa positiva y finita.")
        return rate

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

    def _aware_datetime(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
