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
class RecommendationScenarioInput:
    name: str
    eps_cagr: float
    exit_pe: float
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class RecommendationScenarioOutcome:
    name: str
    eps_cagr: float
    exit_pe: float
    terminal_eps: float
    terminal_price: float
    total_return: float
    annualized_return: float
    available_at: str
    source: str
    source_ref: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "epsCagr": self.eps_cagr,
            "exitPe": self.exit_pe,
            "terminalEps": self.terminal_eps,
            "terminalPrice": self.terminal_price,
            "totalReturn": self.total_return,
            "annualizedReturn": self.annualized_return,
            "availableAt": self.available_at,
            "source": self.source,
            "sourceRef": self.source_ref,
        }


@dataclass(frozen=True)
class RecommendationScenarioAsymmetry:
    status: str
    symbol: str
    instrument_id: int | None
    as_of: str
    horizon_years: int
    latest_price: float | None
    annual_diluted_eps: float | None
    required_return: float
    implied_eps_cagr_at_base_multiple: float | None
    scenarios: tuple[RecommendationScenarioOutcome, ...]
    upside_from_current: float | None
    downside_from_current: float | None
    upside_downside_ratio: float | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "asOf": self.as_of,
            "horizonYears": self.horizon_years,
            "latestPrice": self.latest_price,
            "annualDilutedEps": self.annual_diluted_eps,
            "requiredReturn": self.required_return,
            "impliedEpsCagrAtBaseMultiple": self.implied_eps_cagr_at_base_multiple,
            "scenarios": [scenario.to_api_dict() for scenario in self.scenarios],
            "upsideFromCurrent": self.upside_from_current,
            "downsideFromCurrent": self.downside_from_current,
            "upsideDownsideRatio": self.upside_downside_ratio,
            "advisoryStatus": "no_advice",
            "productionEligible": self.production_eligible,
            "isWeightingReady": False,
            "reason": self.reason,
            "policy": {
                "temporal": "every_scenario_available_at_must_be_lte_as_of",
                "provenance": "every_scenario_requires_explicit_source_and_source_ref",
                "probabilities": "not_assigned_no_expected_value_without_calibrated_probabilities",
                "scenarioOrdering": "bear_lte_base_lte_bull_by_annualized_return",
                "interpretation": "research_asymmetry_diagnostic_not_buy_sell_or_hold_signal",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationScenarioAsymmetryService:
    """Evaluate explicit PIT bear/base/bull valuation outcomes without probabilities.

    The service uses Reverse Valuation only as a PIT evidence anchor for current
    price, EPS, identity and the growth hurdle at the base exit multiple. Scenario
    growth and multiples are caller-supplied and provenance-bound. No probability,
    expected value, action, score, conviction or production weighting is inferred.
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
        bear: RecommendationScenarioInput,
        base: RecommendationScenarioInput,
        bull: RecommendationScenarioInput,
    ) -> RecommendationScenarioAsymmetry:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        cutoff = self._aware_utc(as_of, "as_of")
        years = self._positive_int(horizon_years, "horizon_years")
        required = self._finite(required_return, "required_return")
        if required <= -1.0 or required > 2.0:
            raise ValueError("required_return debe estar en (-1, 2].")

        scenarios = (
            self._validate_scenario(bear, expected_name="bear", as_of=cutoff),
            self._validate_scenario(base, expected_name="base", as_of=cutoff),
            self._validate_scenario(bull, expected_name="bull", as_of=cutoff),
        )

        anchor = self._reverse_valuation_service.evaluate(
            symbol=normalized_symbol,
            as_of=cutoff,
            horizon_years=years,
            required_return=required,
            exit_pe=scenarios[1].exit_pe,
        )
        payload = self._payload(anchor)
        self._assert_upstream_contract(payload, symbol=normalized_symbol, as_of=cutoff)

        instrument_id = self._optional_int(payload.get("instrumentId"))
        price = self._optional_finite(payload.get("latestPrice"), "latestPrice")
        eps = self._optional_finite(payload.get("annualDilutedEps"), "annualDilutedEps")
        implied = self._optional_finite(payload.get("impliedEpsCagr"), "impliedEpsCagr")

        if payload.get("status") != "diagnostic_ready" or price is None or eps is None or price <= 0 or eps <= 0:
            return RecommendationScenarioAsymmetry(
                status="valuation_evidence_not_ready",
                symbol=normalized_symbol,
                instrument_id=instrument_id,
                as_of=cutoff.isoformat(),
                horizon_years=years,
                latest_price=price,
                annual_diluted_eps=eps,
                required_return=required,
                implied_eps_cagr_at_base_multiple=implied,
                scenarios=(),
                upside_from_current=None,
                downside_from_current=None,
                upside_downside_ratio=None,
                production_eligible=False,
                reason="Scenario Asymmetry requiere precio y EPS PIT positivos validados por Reverse Valuation.",
            )

        outcomes = tuple(self._outcome(item, eps=eps, price=price, years=years) for item in scenarios)
        annualized = [item.annualized_return for item in outcomes]
        if not (annualized[0] <= annualized[1] <= annualized[2]):
            raise ValueError(
                "Los escenarios están mal etiquetados: el retorno anualizado debe cumplir bear <= base <= bull."
            )

        downside = max(0.0, -outcomes[0].total_return)
        upside = max(0.0, outcomes[2].total_return)
        ratio = None if downside == 0.0 else self._finite(upside / downside, "upside_downside_ratio")

        return RecommendationScenarioAsymmetry(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            as_of=cutoff.isoformat(),
            horizon_years=years,
            latest_price=price,
            annual_diluted_eps=eps,
            required_return=required,
            implied_eps_cagr_at_base_multiple=implied,
            scenarios=outcomes,
            upside_from_current=self._finite(upside, "upside_from_current"),
            downside_from_current=self._finite(downside, "downside_from_current"),
            upside_downside_ratio=ratio,
            production_eligible=False,
            reason=(
                "Compara resultados explícitos bear/base/bull frente al precio PIT sin asignar probabilidades; "
                "la asimetría observada no constituye señal de compra, venta o mantenimiento."
            ),
        )

    def _validate_scenario(
        self,
        value: RecommendationScenarioInput,
        *,
        expected_name: str,
        as_of: datetime,
    ) -> RecommendationScenarioInput:
        if not isinstance(value, RecommendationScenarioInput):
            raise ValueError(f"{expected_name} debe ser RecommendationScenarioInput.")
        name = str(value.name or "").strip().lower()
        if name != expected_name:
            raise ValueError(f"El escenario {expected_name} debe estar etiquetado exactamente como {expected_name}.")
        growth = self._finite(value.eps_cagr, f"{expected_name}.eps_cagr")
        if growth <= -1.0 or growth > 10.0:
            raise ValueError(f"{expected_name}.eps_cagr debe estar en (-1, 10].")
        multiple = self._finite(value.exit_pe, f"{expected_name}.exit_pe")
        if multiple <= 0.0 or multiple > 500.0:
            raise ValueError(f"{expected_name}.exit_pe debe estar en (0, 500].")
        available_at = self._aware_utc(value.available_at, f"{expected_name}.available_at")
        if available_at > as_of:
            raise ValueError(f"{expected_name}.available_at no puede ser posterior a as_of; evitar look-ahead es obligatorio.")
        source = self._required_text(value.source, f"{expected_name}.source")
        source_ref = self._required_text(value.source_ref, f"{expected_name}.source_ref")
        return RecommendationScenarioInput(
            name=name,
            eps_cagr=growth,
            exit_pe=multiple,
            available_at=available_at,
            source=source,
            source_ref=source_ref,
        )

    def _outcome(
        self,
        scenario: RecommendationScenarioInput,
        *,
        eps: float,
        price: float,
        years: int,
    ) -> RecommendationScenarioOutcome:
        terminal_eps = self._finite(eps * ((1.0 + scenario.eps_cagr) ** years), "terminal_eps")
        terminal_price = self._finite(terminal_eps * scenario.exit_pe, "terminal_price")
        total_return = self._finite(terminal_price / price - 1.0, "total_return")
        annualized_return = self._finite((terminal_price / price) ** (1.0 / years) - 1.0, "annualized_return")
        return RecommendationScenarioOutcome(
            name=scenario.name,
            eps_cagr=scenario.eps_cagr,
            exit_pe=scenario.exit_pe,
            terminal_eps=terminal_eps,
            terminal_price=terminal_price,
            total_return=total_return,
            annualized_return=annualized_return,
            available_at=scenario.available_at.isoformat(),
            source=scenario.source,
            source_ref=scenario.source_ref,
        )

    def _payload(self, diagnostic: object) -> dict[str, Any]:
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("Reverse Valuation no respeta el contrato.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("Reverse Valuation devolvió un contrato inválido.")
        return dict(payload)

    def _assert_upstream_contract(self, payload: dict[str, Any], *, symbol: str, as_of: datetime) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise RuntimeError("Reverse Valuation violó el contrato no-advice.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("Reverse Valuation intentó declararse productiva.")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or policy.get("automaticTrading") is not False:
            raise RuntimeError("Reverse Valuation devolvió una política de trading inválida.")
        if str(payload.get("symbol") or "").strip().upper() != symbol:
            raise RuntimeError("Reverse Valuation devolvió otro símbolo.")
        if self._parse_aware_datetime(payload.get("asOf")) != as_of:
            raise RuntimeError("Reverse Valuation usó otro corte temporal.")

    def _required_text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para preservar provenance.")
        return text

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
            raise RuntimeError("Reverse Valuation no incluye asOf.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("Reverse Valuation incluye asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("Reverse Valuation incluye asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
