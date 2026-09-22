from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.services.dividend_analysis_service import DividendAnalysisService
from app.services.recommendation_market_signal_service import RecommendationMarketSignalService
from app.services.recommendation_valuation_signal_service import RecommendationValuationSignalService


class _MarketDiagnosticService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


class _ValuationDiagnosticService(Protocol):
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
    price_return_60d: float | None
    total_return_60d: float | None
    earnings_payout_ratio: float | None
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
            "priceReturn60d": self.price_return_60d,
            "totalReturn60d": self.total_return_60d,
            "earningsPayoutRatio": self.earnings_payout_ratio,
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "temporal": "same_as_of_for_market_price_and_dividend_knowledge",
                "yield": "trailing_dividend_cash_divided_by_explicit_pit_price",
                "currency": "yield_blocked_when_dividend_currency_is_inconsistent",
                "totalReturn": "price_return_60d_plus_trailing_dividend_yield_diagnostic",
                "sustainability": "earnings_payout_only_when_pit_annual_eps_is_positive_and_currency_compatible",
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
        valuation_service: _ValuationDiagnosticService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._market_service = market_service or RecommendationMarketSignalService(database=self._database)
        self._dividend_service = dividend_service or DividendAnalysisService(database=self._database)
        self._valuation_service = valuation_service or RecommendationValuationSignalService(
            database=self._database,
            market_service=self._market_service,
        )

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
            price_return_60d=self._optional_float(market.get("return60d")),
            earnings_payout_ratio=None,
        )
        if str(market.get("status") or "") != "diagnostic_ready" or instrument_id is None or latest_price is None or latest_price <= 0:
            return RecommendationDividendSignal(
                status="market_evidence_not_ready",
                dividend=None,
                total_return_60d=None,
                reason="El análisis de dividendos requiere primero un precio point-in-time válido y trazable.",
                **common,
            )

        dividend = self._dividend_service.analyze(
            instrument_id=instrument_id,
            knowledge_cutoff=as_of_utc,
            pit_price=latest_price,
        ).to_api_dict()
        price_return_60d = self._optional_float(market.get("return60d"))
        dividend_yield = self._optional_float(dividend.get("trailingYield"))
        total_return_60d = (
            price_return_60d + dividend_yield
            if price_return_60d is not None and dividend_yield is not None
            else None
        )
        earnings_payout_ratio = self._earnings_payout_ratio(
            symbol=normalized_symbol,
            as_of=as_of_utc,
            dividend=dividend,
        )
        status = "diagnostic_ready" if dividend.get("frequency") != "none" else "no_dividend_history"
        return RecommendationDividendSignal(
            status=status,
            dividend=dividend,
            total_return_60d=total_return_60d,
            earnings_payout_ratio=earnings_payout_ratio,
            reason=(
                "Dividendos, yield y retorno total diagnóstico están ligados al mismo corte point-in-time; no constituyen una recomendación."
                if status == "diagnostic_ready"
                else "No existe historial de dividendos conocido en el corte point-in-time analizado."
            ),
            **common,
        )

    def _earnings_payout_ratio(
        self,
        *,
        symbol: str,
        as_of: datetime,
        dividend: dict[str, Any],
    ) -> float | None:
        cash = self._optional_float(dividend.get("annualizedCashPerShare"))
        currency = self._optional_text(dividend.get("currency"))
        if cash is None or cash < 0 or currency is None:
            return None
        diagnostic = self._valuation_service.evaluate(symbol=symbol, as_of=as_of)
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El diagnóstico de valoración no respeta el contrato.")
        payload = to_api_dict()
        if not isinstance(payload, dict) or payload.get("productionEligible") is not False:
            raise RuntimeError("El diagnóstico de valoración devolvió un contrato inválido.")
        if str(payload.get("symbol") or "").strip().upper() != symbol:
            raise RuntimeError("El diagnóstico de valoración devolvió otro símbolo.")
        if self._parse_aware_datetime(payload.get("asOf")) != as_of:
            raise RuntimeError("El diagnóstico de valoración usó otro corte point-in-time.")
        eps = payload.get("annualDilutedEps")
        if not isinstance(eps, dict):
            return None
        eps_value = self._optional_float(eps.get("value"))
        eps_unit = self._optional_text(eps.get("unit"))
        if eps_value is None or eps_value <= 0 or eps_unit is None:
            return None
        normalized_unit = eps_unit.lower().replace(" ", "")
        if normalized_unit not in {f"{currency.lower()}/share", f"{currency.lower()}/shares"}:
            return None
        return cash / eps_value

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
