from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: str
    effective_at: datetime
    value: float
    source_provider: str
    retrieved_at: datetime


class CorporateActionService:
    """Extracts corporate actions without introducing point-in-time leakage.

    Historical providers can expose splits/dividends retrospectively. An action is
    therefore only eligible for a PIT calculation when ATHENA had already retrieved
    that observation and the action was already effective at the knowledge cutoff.
    """

    _SUPPORTED_TYPES = frozenset({"dividend", "stock_split"})

    def extract_from_history(
        self,
        observations: Iterable[dict[str, Any]],
    ) -> tuple[CorporateAction, ...]:
        actions: list[CorporateAction] = []

        for observation in observations:
            symbol = self._required_text(observation.get("symbol"), "symbol").upper()
            provider = self._required_text(
                observation.get("sourceProvider"),
                "sourceProvider",
            )
            effective_at = self._parse_aware_datetime(
                observation.get("timestamp"),
                "timestamp",
            )
            retrieved_at = self._parse_aware_datetime(
                observation.get("retrievedAt"),
                "retrievedAt",
            )
            if retrieved_at < effective_at:
                raise ValueError(
                    "retrievedAt no puede ser anterior al timestamp observado."
                )

            dividend = self._optional_positive_number(
                observation.get("dividend"),
                "dividend",
            )
            if dividend is not None:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        action_type="dividend",
                        effective_at=effective_at,
                        value=dividend,
                        source_provider=provider,
                        retrieved_at=retrieved_at,
                    )
                )

            stock_split = self._optional_positive_number(
                observation.get("stockSplit"),
                "stockSplit",
            )
            if stock_split is not None:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        action_type="stock_split",
                        effective_at=effective_at,
                        value=stock_split,
                        source_provider=provider,
                        retrieved_at=retrieved_at,
                    )
                )

        actions.sort(
            key=lambda item: (
                item.effective_at,
                item.action_type,
                item.symbol,
                item.source_provider,
            )
        )
        return tuple(actions)

    def visible_as_of(
        self,
        actions: Iterable[CorporateAction],
        *,
        knowledge_cutoff: datetime,
    ) -> tuple[CorporateAction, ...]:
        cutoff = self._ensure_aware_datetime(knowledge_cutoff, "knowledge_cutoff")
        visible: list[CorporateAction] = []

        for action in actions:
            if action.action_type not in self._SUPPORTED_TYPES:
                raise ValueError("Tipo de corporate action no soportado.")
            if action.retrieved_at <= cutoff and action.effective_at <= cutoff:
                visible.append(action)

        visible.sort(
            key=lambda item: (
                item.effective_at,
                item.action_type,
                item.symbol,
                item.source_provider,
            )
        )
        return tuple(visible)

    def cumulative_split_factor(
        self,
        actions: Iterable[CorporateAction],
        *,
        symbol: str,
        knowledge_cutoff: datetime,
    ) -> float:
        normalized_symbol = self._required_text(symbol, "symbol").upper()
        factor = 1.0
        for action in self.visible_as_of(
            actions,
            knowledge_cutoff=knowledge_cutoff,
        ):
            if action.symbol != normalized_symbol:
                continue
            if action.action_type == "stock_split":
                factor *= action.value
        if not math.isfinite(factor) or factor <= 0:
            raise RuntimeError("El factor acumulado de split no es válido.")
        return factor

    def _required_text(self, value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    def _parse_aware_datetime(self, value: Any, field: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{field} debe ser una fecha ISO válida.") from exc
        else:
            raise ValueError(f"{field} es obligatorio.")
        return self._ensure_aware_datetime(parsed, field)

    def _ensure_aware_datetime(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _optional_positive_number(self, value: Any, field: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError(f"{field} no acepta booleanos.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{field} debe ser finito.")
        if number == 0:
            return None
        if number < 0:
            raise ValueError(f"{field} debe ser positivo cuando está presente.")
        return number
