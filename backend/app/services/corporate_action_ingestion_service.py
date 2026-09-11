from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.repositories.corporate_action_repository import CorporateActionRepository
from app.services.corporate_action_service import CorporateAction, CorporateActionService
from app.services.yahoo_market_service import YahooMarketService


class HistoricalMarketProvider(Protocol):
    def get_history(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class CorporateActionIngestionStats:
    history_observations: int
    actions_received: int
    inserted: int
    unchanged: int
    retrieval_batches: int


class CorporateActionIngestionService:
    """Persists corporate actions from provider history without erasing PIT provenance.

    Providers such as Yahoo expose old dividends and splits retrospectively. Each
    retrieval is therefore persisted using the exact provider/retrieved-at pair
    present in the historical response. Re-fetching the same immutable observation
    is idempotent, while a later retrieval remains a separate PIT observation.
    """

    def __init__(
        self,
        *,
        market_provider: HistoricalMarketProvider | None = None,
        action_service: CorporateActionService | None = None,
        repository: CorporateActionRepository | None = None,
    ) -> None:
        self._market_provider = (
            market_provider if market_provider is not None else YahooMarketService()
        )
        self._action_service = (
            action_service if action_service is not None else CorporateActionService()
        )
        self._repository = (
            repository if repository is not None else CorporateActionRepository()
        )

    def ingest_history(
        self,
        *,
        instrument_id: int,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
        dividend_currency: str | None = None,
    ) -> CorporateActionIngestionStats:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")

        normalized_symbol = self._required_text(symbol, "symbol").upper()
        normalized_currency = self._normalize_currency(dividend_currency)

        history = self._market_provider.get_history(
            normalized_symbol,
            from_date=from_date,
            to_date=to_date,
        )
        if not history:
            return CorporateActionIngestionStats(
                history_observations=0,
                actions_received=0,
                inserted=0,
                unchanged=0,
                retrieval_batches=0,
            )

        actions = self._action_service.extract_from_history(history)
        if not actions:
            return CorporateActionIngestionStats(
                history_observations=len(history),
                actions_received=0,
                inserted=0,
                unchanged=0,
                retrieval_batches=0,
            )

        for action in actions:
            if action.symbol != normalized_symbol:
                raise ValueError(
                    "El proveedor devolvió corporate actions de un símbolo distinto."
                )

        batches: dict[tuple[str, datetime], list[CorporateAction]] = {}
        for action in actions:
            retrieved_at = action.retrieved_at.astimezone(timezone.utc)
            key = (action.source_provider, retrieved_at)
            batches.setdefault(key, []).append(action)

        inserted = 0
        unchanged = 0
        for (provider, retrieved_at), batch in sorted(
            batches.items(),
            key=lambda item: (item[0][1], item[0][0]),
        ):
            payload = [
                self._to_repository_payload(
                    action,
                    dividend_currency=normalized_currency,
                )
                for action in batch
            ]
            stats = self._repository.save_many(
                instrument_id=instrument_id,
                actions=payload,
                source_provider=provider,
                retrieved_at=retrieved_at,
            )
            inserted += stats.inserted
            unchanged += stats.unchanged

        return CorporateActionIngestionStats(
            history_observations=len(history),
            actions_received=len(actions),
            inserted=inserted,
            unchanged=unchanged,
            retrieval_batches=len(batches),
        )

    def _to_repository_payload(
        self,
        action: CorporateAction,
        *,
        dividend_currency: str | None,
    ) -> dict[str, object | None]:
        if action.action_type == "dividend":
            return {
                "action_type": "dividend",
                "effective_at": action.effective_at,
                "cash_amount": action.value,
                "split_ratio": None,
                "currency": dividend_currency,
                "source_timestamp": action.effective_at,
            }
        if action.action_type == "stock_split":
            return {
                "action_type": "split",
                "effective_at": action.effective_at,
                "cash_amount": None,
                "split_ratio": action.value,
                "currency": None,
                "source_timestamp": action.effective_at,
            }
        raise ValueError("Tipo de corporate action no soportado para persistencia.")

    def _required_text(self, value: object, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _normalize_currency(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("dividend_currency no puede estar vacía.")
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("dividend_currency debe ser un código ISO de tres letras.")
        return normalized
