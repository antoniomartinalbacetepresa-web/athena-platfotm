from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.services.dividend_analysis_service import DividendAnalysisService
from app.services.recommendation_market_signal_service import RecommendationMarketSignalService


class _MarketDiagnosticService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


@dataclass(frozen=True)
class RecommendationDividendSignal:
    status: str
    symbol: str
    instrument_id: int | None
    as_of: str
    latest_price: float | None
    latest_price_observed_at: str | None
    latest_price_retrieved_at: str | None
    market_source_providers: tuple[str, ...]
    dividend: dict[str, Any] | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "latestPrice": self.latest_price,
            "latestPriceObservedAt": self.latest_price_observed_at,
            "latestPriceRetrievedAt": self.latest_price_retrieved_at,
            "marketSourceProviders": list(self.market_source_providers),
            "dividend": self.dividend,
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "temporal": "same_as_of_for_market_price_and_dividend_knowledge",
                "yield": "trailing_dividend_cash_divided_by_explicit_pit_price",
                "currency": "yield_blocked_when_dividend_currency_is_inconsistent",
                "authority": "diagnostic_only_not_buy_sell_or_trading_authority",
            },
        }


class RecommendationDividendSignalService:
    """Bind dividend evidence to the same PIT price used by market diagnostics."""

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        market_service: _MarketDiagnosticService | None = None,
        dividend_service: DividendAnalysisService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._market_service = market_service or RecommendationMarketSignalService(database=self._database)
        self._dividend_service = dividend_service or DividendAnalysisService(database=self._database)

    def evaluate(self, *, symbol: str, as_of: datetime) -> RecommendationDividendSignal:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)
        diagnostic = self._market_service.evaluate(symbol=normalized_symbol, as_of=as_of_utc)
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El diagnóstico de mercado no respeta el contrato.")
        market = to_api_dict()
        if not isinstance(market, dict) or market.get("productionEligible") is not False:
            raise RuntimeError("El diagnóstico de mercado devolvió un contrato inválido.")
        if str(market.get("symbol") or "").strip().upper() != normalized_symbol:
            raise RuntimeError("El diagnóstico de mercado devolvió otro símbolo.")
        component_as_of = self._parse_aware_datetime(market.get("asOf"))
        if component_as_of != as_of_utc:
            raise RuntimeError("El diagnóstico de mercado usó otro corte point-in-time.")

        instrument_id = self._optional_int(market.get("instrumentId"))
        latest_price = self._optional_float(market.get("latestPrice"))
        providers = market.get("sourceProviders")
        source_providers = tuple(sorted({str(item).strip() for item in providers if str(item).strip()})) if isinstance(providers, list) else ()
        common = dict(
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            as_of=as_of_utc.isoformat(),
            latest_price=latest_price,
            latest_price_observed_at=self._optional_text(market.get("latestObservedAt")),
            latest_price_retrieved_at=self._optional_text(market.get("latestRetrievedAt")),
            market_source_providers=source_providers,
            production_eligible=False,
        )
        if str(market.get("status") or "") != "diagnostic_ready" or instrument_id is None or latest_price is None or latest_price <= 0:
            return RecommendationDividendSignal(
                status="market_evidence_not_ready",
                dividend=None,
                reason="El análisis de dividendos requiere primero un precio point-in-time válido y trazable.",
                **common,
            )

        dividend = self._dividend_service.analyze(
            instrument_id=instrument_id,
            knowledge_cutoff=as_of_utc,
            pit_price=latest_price,
        ).to_api_dict()
        status = "diagnostic_ready" if dividend.get("frequency") != "none" else "no_dividend_history"
        return RecommendationDividendSignal(
            status=status,
            dividend=dividend,
            reason=(
                "Dividendos y yield están ligados al mismo corte point-in-time del precio; son evidencia diagnóstica y no una recomendación."
                if status == "diagnostic_ready"
                else "No existe historial de dividendos conocido en el corte point-in-time analizado."
            ),
            **common,
        )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_aware_datetime(value: object) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("El diagnóstico de mercado incluye asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("El diagnóstico de mercado incluye asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None
