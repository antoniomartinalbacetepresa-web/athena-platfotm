from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class _ReverseValuationService(Protocol):
    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        horizon_years: int,
        required_return: float,
        exit_pe: float,
    ) -> object: ...


@dataclass(frozen=True)
class RecommendationExpectationsGap:
    status: str
    symbol: str
    instrument_id: int | None
    as_of: str
    implied_eps_cagr: float | None
    reference_eps_cagr: float
    expectations_gap: float | None
    expectation_available_at: str
    expectation_source: str
    expectation_source_ref: str
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "impliedEpsCagr": self.implied_eps_cagr,
            "referenceExpectation": {
                "epsCagr": self.reference_eps_cagr,
                "availableAt": self.expectation_available_at,
                "source": self.expectation_source,
                "sourceRef": self.expectation_source_ref,
            },
            "expectationsGap": self.expectations_gap,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "isWeightingReady": False,
            "reason": self.reason,
            "policy": {
                "temporal": "reference_expectation_available_at_must_be_lte_as_of",
                "referenceExpectation": "explicit_caller_supplied_with_provenance_no_hidden_consensus",
                "gapFormula": "reference_eps_cagr_minus_price_implied_eps_cagr",
                "interpretation": "signed_expectations_difference_not_buy_sell_signal",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationExpectationsGapService:
    """Compare a PIT growth expectation with the price-implied growth hurdle.

    The reference expectation is deliberately supplied explicitly by the caller
    together with its availability timestamp and provenance. This prevents ATHENA
    from silently using today's analyst consensus when evaluating a historical
    point in time. The output is a research diagnostic only: it does not assign
    actions, scores, conviction or production eligibility.
    """

    def __init__(self, *, reverse_valuation_service: _ReverseValuationService) -> None:
        self._reverse_valuation_service = reverse_valuation_service

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        horizon_years: int,
        required_return: float,
        exit_pe: float,
        reference_eps_cagr: float,
        expectation_available_at: datetime,
        expectation_source: str,
        expectation_source_ref: str,
    ) -> RecommendationExpectationsGap:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")

        cutoff = self._aware_utc(as_of, "as_of")
        available_at = self._aware_utc(
            expectation_available_at,
            "expectation_available_at",
        )
        if available_at > cutoff:
            raise ValueError(
                "expectation_available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio."
            )

        reference_growth = self._finite(reference_eps_cagr, "reference_eps_cagr")
        if reference_growth <= -1.0 or reference_growth > 10.0:
            raise ValueError("reference_eps_cagr debe estar en (-1, 10].")

        source = self._required_text(expectation_source, "expectation_source")
        source_ref = self._required_text(expectation_source_ref, "expectation_source_ref")

        diagnostic = self._reverse_valuation_service.evaluate(
            symbol=normalized_symbol,
            as_of=cutoff,
            horizon_years=horizon_years,
            required_return=required_return,
            exit_pe=exit_pe,
        )
        payload = self._payload(diagnostic)
        self._assert_upstream_contract(payload, symbol=normalized_symbol, as_of=cutoff)

        instrument_id = self._optional_int(payload.get("instrumentId"))
        implied_growth = self._optional_finite(
            payload.get("impliedEpsCagr"),
            "impliedEpsCagr",
        )

        if payload.get("status") != "diagnostic_ready" or implied_growth is None:
            return RecommendationExpectationsGap(
                status="reverse_valuation_not_ready",
                symbol=normalized_symbol,
                instrument_id=instrument_id,
                as_of=cutoff.isoformat(),
                implied_eps_cagr=implied_growth,
                reference_eps_cagr=reference_growth,
                expectations_gap=None,
                expectation_available_at=available_at.isoformat(),
                expectation_source=source,
                expectation_source_ref=source_ref,
                production_eligible=False,
                reason=(
                    "No existe todavía una valoración inversa PIT suficiente para calcular "
                    "la brecha de expectativas."
                ),
            )

        gap = self._finite(
            reference_growth - implied_growth,
            "expectations_gap",
        )
        return RecommendationExpectationsGap(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            as_of=cutoff.isoformat(),
            implied_eps_cagr=implied_growth,
            reference_eps_cagr=reference_growth,
            expectations_gap=gap,
            expectation_available_at=available_at.isoformat(),
            expectation_source=source,
            expectation_source_ref=source_ref,
            production_eligible=False,
            reason=(
                "Diferencia entre una expectativa de crecimiento EPS disponible en el corte PIT "
                "y el crecimiento exigido por el precio bajo el escenario explícito; no es señal "
                "de compra/venta ni recomendación."
            ),
        )

    def _payload(self, diagnostic: object) -> dict[str, Any]:
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("La valoración inversa no respeta el contrato.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("La valoración inversa devolvió un contrato inválido.")
        return dict(payload)

    def _assert_upstream_contract(
        self,
        payload: dict[str, Any],
        *,
        symbol: str,
        as_of: datetime,
    ) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise RuntimeError("La valoración inversa violó el contrato no-advice.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("La valoración inversa intentó declararse productiva.")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise RuntimeError("La valoración inversa devolvió una política de trading inválida.")
        if str(payload.get("symbol") or "").strip().upper() != symbol:
            raise RuntimeError("La valoración inversa devolvió otro símbolo.")
        component_as_of = self._parse_aware_datetime(payload.get("asOf"))
        if component_as_of != as_of:
            raise RuntimeError("La valoración inversa usó otro corte temporal.")

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar provenance.")
        return text

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
            raise RuntimeError("La valoración inversa no incluye asOf.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("La valoración inversa incluye asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("La valoración inversa incluye asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
