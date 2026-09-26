from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class _ValuationSignalService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


@dataclass(frozen=True)
class RecommendationReverseValuation:
    status: str
    symbol: str
    instrument_id: int | None
    as_of: str
    latest_price: float | None
    annual_diluted_eps: float | None
    horizon_years: int
    required_return: float
    exit_pe: float
    required_terminal_eps: float | None
    implied_eps_cagr: float | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "latestPrice": self.latest_price,
            "annualDilutedEps": self.annual_diluted_eps,
            "assumptions": {
                "horizonYears": self.horizon_years,
                "requiredReturn": self.required_return,
                "exitPe": self.exit_pe,
            },
            "requiredTerminalEps": self.required_terminal_eps,
            "impliedEpsCagr": self.implied_eps_cagr,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "policy": {
                "temporal": "inherits_exact_point_in_time_cutoff_from_valuation_signal",
                "assumptions": "explicit_caller_supplied_no_hidden_defaults",
                "identity": "inherits_instrument_and_sec_issuer_binding_from_valuation_signal",
                "formula": "price_times_required_return_compounding_divided_by_exit_pe_then_eps_cagr",
                "interpretation": "required_growth_diagnostic_not_fair_value_target_or_advice",
                "automaticTrading": False,
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationReverseValuationService:
    """Reverse an explicit earnings-multiple scenario without inventing a fair value.

    The service deliberately has no assumption defaults. A caller must state the
    horizon, required return and exit P/E. The underlying current price and annual
    diluted EPS come from ATHENA's PIT valuation diagnostic, preserving its
    temporal, identity and provenance gates.
    """

    def __init__(self, *, valuation_service: _ValuationSignalService) -> None:
        self._valuation_service = valuation_service

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        horizon_years: int,
        required_return: float,
        exit_pe: float,
    ) -> RecommendationReverseValuation:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        cutoff = self._aware_utc(as_of)
        years = self._positive_int(horizon_years, "horizon_years")
        required = self._finite(required_return, "required_return")
        multiple = self._finite(exit_pe, "exit_pe")
        if required <= -1.0 or required > 2.0:
            raise ValueError("required_return debe estar en (-1, 2].")
        if multiple <= 0.0 or multiple > 500.0:
            raise ValueError("exit_pe debe estar en (0, 500].")

        diagnostic = self._valuation_service.evaluate(symbol=normalized_symbol, as_of=cutoff)
        payload = self._payload(diagnostic)
        self._assert_upstream_contract(payload, symbol=normalized_symbol, as_of=cutoff)
        instrument_id = self._optional_int(payload.get("instrumentId"))
        price = self._optional_finite(payload.get("latestPrice"), "latestPrice")
        eps_payload = payload.get("annualDilutedEps")
        eps = None
        if isinstance(eps_payload, dict):
            eps = self._optional_finite(eps_payload.get("value"), "annualDilutedEps.value")

        if payload.get("status") != "diagnostic_ready" or price is None or eps is None or eps <= 0.0:
            return RecommendationReverseValuation(
                status="valuation_evidence_not_ready",
                symbol=normalized_symbol,
                instrument_id=instrument_id,
                as_of=cutoff.isoformat(),
                latest_price=price,
                annual_diluted_eps=eps,
                horizon_years=years,
                required_return=required,
                exit_pe=multiple,
                required_terminal_eps=None,
                implied_eps_cagr=None,
                production_eligible=False,
                reason="La valoración inversa requiere precio y EPS anual positivo PIT ya validados.",
            )

        required_terminal_eps = price * ((1.0 + required) ** years) / multiple
        implied_eps_cagr = (required_terminal_eps / eps) ** (1.0 / years) - 1.0
        required_terminal_eps = self._finite(required_terminal_eps, "required_terminal_eps")
        implied_eps_cagr = self._finite(implied_eps_cagr, "implied_eps_cagr")
        return RecommendationReverseValuation(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            as_of=cutoff.isoformat(),
            latest_price=price,
            annual_diluted_eps=eps,
            horizon_years=years,
            required_return=required,
            exit_pe=multiple,
            required_terminal_eps=required_terminal_eps,
            implied_eps_cagr=implied_eps_cagr,
            production_eligible=False,
            reason=(
                "Crecimiento de EPS exigido por el escenario explícito para reconciliar el precio PIT; "
                "no es valor razonable, precio objetivo ni recomendación."
            ),
        )

    def _payload(self, diagnostic: object) -> dict[str, Any]:
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El diagnóstico de valoración no respeta el contrato.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("El diagnóstico de valoración devolvió un contrato inválido.")
        return dict(payload)

    def _assert_upstream_contract(self, payload: dict[str, Any], *, symbol: str, as_of: datetime) -> None:
        if payload.get("productionEligible") is not False:
            raise RuntimeError("La valoración PIT intentó declararse productiva.")
        if str(payload.get("symbol") or "").strip().upper() != symbol:
            raise RuntimeError("La valoración PIT devolvió otro símbolo.")
        component_as_of = self._parse_aware_datetime(payload.get("asOf"))
        if component_as_of != as_of:
            raise RuntimeError("La valoración PIT usó otro corte temporal.")

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser un entero positivo.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser un entero positivo.") from exc
        if parsed <= 0 or parsed > 50 or parsed != value:
            raise ValueError(f"{field} debe ser un entero entre 1 y 50.")
        return parsed

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser numérico finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser numérico finito.")
        return result

    def _optional_finite(self, value: object, field: str) -> float | None:
        if value is None:
            return None
        return self._finite(value, field)

    def _optional_int(self, value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_aware_datetime(self, value: object) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError("La valoración PIT no incluye asOf.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("La valoración PIT incluye asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("La valoración PIT incluye asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
