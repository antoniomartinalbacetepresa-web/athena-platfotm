from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    """Persists corporate actions from provider history without erasing PIT provenance."""

    def __init__(
        self,
        *,
        market_provider: HistoricalMarketProvider | None = None,
        action_service: CorporateActionService | None = None,
        repository: CorporateActionRepository | None = None,
    ) -> None:
        self._market_provider = market_provider if market_provider is not None else YahooMarketService()
        self._action_service = action_service if action_service is not None else CorporateActionService()
        self._repository = repository if repository is not None else CorporateActionRepository()

    def ingest_history(
        self,
        *,
        instrument_id: int,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
        dividend_currency: str | None = None,
        expected_source_provider: str | None = None,
    ) -> CorporateActionIngestionStats:
        if instrument_id <= 0:
            raise ValueError("instrument_id debe ser positivo.")

        normalized_symbol = self._required_text(symbol, "symbol").upper()
        normalized_currency = self._normalize_currency(dividend_currency)
        normalized_expected_provider = (
            self._required_text(expected_source_provider, "expected_source_provider").lower()
            if expected_source_provider is not None
            else None
        )

        # Validate requested economic dates before network I/O. An open upper
        # bound with an explicit lower bound is capped to today's UTC date.
        lower = self._window_date(from_date, "from_date")
        upper = self._window_date(to_date, "to_date")
        today = datetime.now(timezone.utc).date()
        if upper is not None and upper > today:
            raise ValueError("to_date no puede ser futura.")
        if lower is not None and upper is None:
            upper = today
        if lower is not None and upper is not None and lower > upper:
            raise ValueError("from_date no puede superar to_date.")
        requested_to_date = upper.isoformat() if to_date is None and lower is not None else to_date

        # Bind the provider request to the canonical stored instrument before
        # any external retrieval or write. Provider-symbol validation alone is
        # insufficient when a caller supplies the wrong instrument_id.
        self._repository.require_instrument_symbol(
            instrument_id=instrument_id,
            symbol=normalized_symbol,
        )

        history = self._market_provider.get_history(
            normalized_symbol,
            from_date=from_date,
            to_date=requested_to_date,
        )
        if not history:
            return CorporateActionIngestionStats(0, 0, 0, 0, 0)

        # Validate the complete provider response, not just rows with actions.
        # The provider's own date filtering and clock are not authority
        # boundaries: one invalid row rejects the instrument before any write.
        received_at = datetime.now(timezone.utc)
        # Otherwise an unrelated symbol/provider with no dividend or split can
        # silently masquerade as a legitimate empty retrieval.
        for observation in history:
            if not isinstance(observation, dict):
                raise ValueError("La historia contiene una observación no estructurada.")
            observation_symbol = self._required_text(
                observation.get("symbol"), "symbol"
            ).upper()
            if observation_symbol != normalized_symbol:
                raise ValueError(
                    "El proveedor devolvió historia de un símbolo distinto."
                )
            effective_at = self._aware_timestamp(observation.get("timestamp"), "timestamp")
            retrieved_at = self._aware_timestamp(observation.get("retrievedAt"), "retrievedAt")
            if effective_at > received_at or retrieved_at > received_at:
                raise ValueError("Corporate action contiene conocimiento futuro.")
            if retrieved_at < effective_at:
                raise ValueError("retrievedAt no puede ser anterior al timestamp observado.")
            day = effective_at.date()
            if (lower is not None and day < lower) or (upper is not None and day > upper):
                raise ValueError("Corporate action fuera de la ventana PIT solicitada.")
            if normalized_expected_provider is not None:
                observation_provider = self._required_text(
                    observation.get("sourceProvider"), "sourceProvider"
                ).lower()
                if observation_provider != normalized_expected_provider:
                    raise ValueError(
                        "Corporate action provenance mismatch: provider identity rejected."
                    )

        actions = self._action_service.extract_from_history(history)
        if not actions:
            return CorporateActionIngestionStats(len(history), 0, 0, 0, 0)

        for action in actions:
            if action.symbol != normalized_symbol:
                raise ValueError("El proveedor devolvió corporate actions de un símbolo distinto.")
            if (
                normalized_expected_provider is not None
                and action.source_provider.strip().lower() != normalized_expected_provider
            ):
                raise ValueError(
                    "Corporate action provenance mismatch: provider identity rejected."
                )

        batches: dict[tuple[str, datetime], list[CorporateAction]] = {}
        for action in actions:
            retrieved_at = action.retrieved_at.astimezone(timezone.utc)
            key = (action.source_provider, retrieved_at)
            batches.setdefault(key, []).append(action)

        inserted = 0
        unchanged = 0
        for (provider, retrieved_at), batch in sorted(
            batches.items(), key=lambda item: (item[0][1], item[0][0])
        ):
            payload = [
                self._to_repository_payload(action, dividend_currency=normalized_currency)
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

    @staticmethod
    def _window_date(value: str | None, field: str) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field} debe usar YYYY-MM-DD.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} debe usar YYYY-MM-DD.") from exc
        if parsed.isoformat() != value:
            raise ValueError(f"{field} debe usar YYYY-MM-DD.")
        return parsed

    @staticmethod
    def _aware_timestamp(value: object, field: str) -> datetime:
        try:
            parsed = (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if isinstance(value, str) else value
            )
        except ValueError as exc:
            raise ValueError(f"{field} debe ser ISO-8601 válido.") from exc
        if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _to_repository_payload(
        self, action: CorporateAction, *, dividend_currency: str | None
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
