from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.recommendation_market_signal_service import (
    RecommendationMarketSignalService,
)


class _MarketDiagnosticService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime) -> object: ...


@dataclass(frozen=True)
class ValuationFact:
    metric: str
    value: float
    unit: str | None
    effective_at: str | None
    available_at: str
    source_version: str | None
    quality_score: float | None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "effectiveAt": self.effective_at,
            "availableAt": self.available_at,
            "sourceVersion": self.source_version,
            "qualityScore": self.quality_score,
        }


@dataclass(frozen=True)
class RecommendationValuationSignal:
    status: str
    symbol: str
    instrument_id: int | None
    entity_id: str | None
    as_of: str
    latest_price: float | None
    latest_price_observed_at: str | None
    latest_price_retrieved_at: str | None
    market_source_providers: tuple[str, ...]
    annual_diluted_eps: ValuationFact | None
    reported_annual_pe: float | None
    production_eligible: bool
    reason: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "instrumentId": self.instrument_id,
            "entityId": self.entity_id,
            "asOf": self.as_of,
            "latestPrice": self.latest_price,
            "latestPriceObservedAt": self.latest_price_observed_at,
            "latestPriceRetrievedAt": self.latest_price_retrieved_at,
            "marketSourceProviders": list(self.market_source_providers),
            "annualDilutedEps": (
                self.annual_diluted_eps.to_api_dict()
                if self.annual_diluted_eps is not None
                else None
            ),
            "reportedAnnualPe": self.reported_annual_pe,
            "productionEligible": self.production_eligible,
            "reason": self.reason,
            "policy": {
                "temporal": (
                    "market_observed_and_retrieved_by_as_of_plus_"
                    "sec_fact_available_by_as_of"
                ),
                "earnings": "latest_available_10k_diluted_eps_only",
                "multiple": "latest_pit_price_divided_by_reported_annual_diluted_eps",
                "negativeOrZeroEps": "pe_not_computed",
                "interpretation": (
                    "reported_annual_pe_is_diagnostic_not_ttm_fair_value_or_advice"
                ),
                "calibration": "not_productive_until_out_of_sample_validated",
            },
        }


class RecommendationValuationSignalService:
    """Build a narrow, point-in-time valuation diagnostic without advice.

    The first defensible multiple is intentionally limited to a reported annual
    P/E: the PIT market price divided by the latest diluted EPS from an SEC 10-K
    that was publicly available at the cutoff. ATHENA must not substitute a
    current market-cap field, infer missing shares, or call this a TTM/fair-value
    estimate.
    """

    _SOURCE_PROVIDER = "sec_edgar"
    _SOURCE_ID = "sec_edgar_xbrl"
    _EPS_METRICS = (
        "fundamental.us-gaap.earningspersharediluted",
        "fundamental.us-gaap.earningspersharebasicanddiluted",
    )

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        market_service: _MarketDiagnosticService | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._identities = IssuerIdentityRepository(database=self._database)
        self._market_service = (
            market_service
            if market_service is not None
            else RecommendationMarketSignalService(database=self._database)
        )

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
    ) -> RecommendationValuationSignal:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol es obligatorio.")
        as_of_utc = self._aware_utc(as_of)
        self._database.initialize()
        self._identities.initialize()

        market_payload = self._market_payload(
            symbol=normalized_symbol,
            as_of=as_of_utc,
        )
        market_status = str(market_payload.get("status") or "")
        instrument_id = self._optional_int(market_payload.get("instrumentId"))
        if market_status != "diagnostic_ready" or instrument_id is None:
            return self._result(
                status="market_evidence_not_ready",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                reason=(
                    "La valoración requiere primero un precio de mercado point-in-time "
                    "con historial y procedencia suficientes."
                ),
            )

        ciks = self._sec_ciks(instrument_id)
        if not ciks:
            return self._result(
                status="issuer_identity_missing",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                reason=(
                    "No existe una identidad SEC inequívoca para enlazar beneficios "
                    "por acción con este instrumento."
                ),
            )
        if len(ciks) != 1:
            return self._result(
                status="issuer_identity_ambiguous",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                reason="Existe más de un CIK SEC candidato para el instrumento.",
            )

        entity_id = f"sec-cik:{ciks[0].zfill(10)}"
        eps = self._latest_annual_diluted_eps(
            entity_id=entity_id,
            as_of=as_of_utc,
        )
        if eps is None:
            return self._result(
                status="valuation_input_missing",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                entity_id=entity_id,
                reason=(
                    "No hay EPS diluido anual SEC (10-K) point-in-time utilizable. "
                    "ATHENA no infiere acciones ni beneficios ausentes."
                ),
            )

        latest_price = self._optional_float(market_payload.get("latestPrice"))
        if latest_price is None or latest_price <= 0:
            return self._result(
                status="market_price_invalid",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                entity_id=entity_id,
                eps=eps,
                reason="El precio point-in-time no es válido para valoración.",
            )

        if eps.value <= 0:
            return self._result(
                status="negative_or_zero_earnings",
                symbol=normalized_symbol,
                as_of=as_of_utc,
                market_payload=market_payload,
                instrument_id=instrument_id,
                entity_id=entity_id,
                eps=eps,
                reason=(
                    "El EPS diluido anual es cero o negativo; un P/E convencional "
                    "no es interpretable y ATHENA no fuerza un múltiplo."
                ),
            )

        reported_annual_pe = latest_price / eps.value
        return self._result(
            status="diagnostic_ready",
            symbol=normalized_symbol,
            as_of=as_of_utc,
            market_payload=market_payload,
            instrument_id=instrument_id,
            entity_id=entity_id,
            eps=eps,
            reported_annual_pe=reported_annual_pe,
            reason=(
                "P/E anual reportado calculado con precio y EPS point-in-time. "
                "Es un múltiplo diagnóstico, no TTM, precio objetivo ni recomendación."
            ),
        )

    def _market_payload(self, *, symbol: str, as_of: datetime) -> dict[str, Any]:
        diagnostic = self._market_service.evaluate(symbol=symbol, as_of=as_of)
        to_api_dict = getattr(diagnostic, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("El diagnóstico de mercado no respeta el contrato.")
        payload = to_api_dict()
        if not isinstance(payload, dict):
            raise RuntimeError("El diagnóstico de mercado devolvió un contrato inválido.")
        if payload.get("productionEligible") is not False:
            raise RuntimeError("El diagnóstico de mercado intentó declararse productivo.")
        if str(payload.get("symbol") or "").strip().upper() != symbol:
            raise RuntimeError("El diagnóstico de mercado devolvió otro símbolo.")
        component_as_of = self._parse_aware_datetime(payload.get("asOf"))
        if component_as_of != as_of:
            raise RuntimeError("El diagnóstico de mercado usó otro corte point-in-time.")
        return dict(payload)

    def _sec_ciks(self, instrument_id: int) -> tuple[str, ...]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT iei.external_id
                FROM instrument_issuer_links iil
                JOIN issuer_external_ids iei
                  ON iei.issuer_id = iil.issuer_id
                WHERE iil.instrument_id = ?
                  AND iei.source_provider = ?
                ORDER BY iei.evidence_confidence DESC, iei.external_id ASC
                """,
                (instrument_id, self._SOURCE_PROVIDER),
            ).fetchall()
        result: list[str] = []
        for row in rows:
            digits = "".join(
                character
                for character in str(row["external_id"])
                if character.isdigit()
            )
            if digits and digits not in result:
                result.append(digits)
        return tuple(result)

    def _latest_annual_diluted_eps(
        self,
        *,
        entity_id: str,
        as_of: datetime,
    ) -> ValuationFact | None:
        placeholders = ",".join("?" for _ in self._EPS_METRICS)
        cutoff = as_of.astimezone(timezone.utc).isoformat()
        with self._database.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(normalized_data_observations)"
                ).fetchall()
            }
            if "available_at" not in columns:
                return None
            rows = connection.execute(
                f"""
                SELECT
                    metric,
                    value_json,
                    unit,
                    effective_at,
                    available_at,
                    source_version,
                    quality_score,
                    id
                FROM normalized_data_observations
                WHERE entity_id = ?
                  AND source_id = ?
                  AND data_kind = 'fact'
                  AND available_at IS NOT NULL
                  AND available_at <= ?
                  AND metric IN ({placeholders})
                  AND UPPER(COALESCE(source_version, '')) LIKE '10-K|%'
                ORDER BY
                    COALESCE(effective_at, '') DESC,
                    CASE metric
                        WHEN ? THEN 0
                        WHEN ? THEN 1
                        ELSE 2
                    END,
                    available_at DESC,
                    id DESC
                """,
                (
                    entity_id,
                    self._SOURCE_ID,
                    cutoff,
                    *self._EPS_METRICS,
                    self._EPS_METRICS[0],
                    self._EPS_METRICS[1],
                ),
            ).fetchall()

        for raw in rows:
            row = dict(raw)
            value = self._numeric_value(row.get("value_json"))
            if value is None:
                continue
            unit = self._optional_text(row.get("unit"))
            if unit is not None and unit.lower() not in {
                "usd/shares",
                "usd/share",
                "usd per share",
            }:
                continue
            return ValuationFact(
                metric=str(row["metric"]),
                value=value,
                unit=unit,
                effective_at=self._optional_text(row.get("effective_at")),
                available_at=str(row["available_at"]),
                source_version=self._optional_text(row.get("source_version")),
                quality_score=self._optional_float(row.get("quality_score")),
            )
        return None

    def _result(
        self,
        *,
        status: str,
        symbol: str,
        as_of: datetime,
        market_payload: dict[str, Any],
        reason: str,
        instrument_id: int | None = None,
        entity_id: str | None = None,
        eps: ValuationFact | None = None,
        reported_annual_pe: float | None = None,
    ) -> RecommendationValuationSignal:
        providers = market_payload.get("sourceProviders")
        source_providers = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in providers
                    if str(item).strip()
                }
            )
            if isinstance(providers, list)
            else ()
        )
        return RecommendationValuationSignal(
            status=status,
            symbol=symbol,
            instrument_id=instrument_id,
            entity_id=entity_id,
            as_of=as_of.isoformat(),
            latest_price=self._optional_float(market_payload.get("latestPrice")),
            latest_price_observed_at=self._optional_text(
                market_payload.get("latestObservedAt")
            ),
            latest_price_retrieved_at=self._optional_text(
                market_payload.get("latestRetrievedAt")
            ),
            market_source_providers=source_providers,
            annual_diluted_eps=eps,
            reported_annual_pe=reported_annual_pe,
            production_eligible=False,
            reason=reason,
        )

    def _numeric_value(self, value_json: object) -> float | None:
        try:
            value = json.loads(str(value_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def _optional_text(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_float(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _optional_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _parse_aware_datetime(self, value: object) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError("El diagnóstico de mercado no incluye asOf.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("El diagnóstico de mercado incluye asOf inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("El diagnóstico de mercado incluye asOf sin zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)
