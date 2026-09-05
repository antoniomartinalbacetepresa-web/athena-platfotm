from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Protocol

from app.repositories.fx_rate_repository import FxRateRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.fx_quote_service import FxQuoteService


class _InstrumentRepository(Protocol):
    def get_by_id(self, instrument_id: int) -> dict[str, Any] | None: ...


class _MarketObservationRepository(Protocol):
    def list_for_instrument(
        self,
        instrument_id: int,
        *,
        source_provider: str | None = None,
        knowledge_cutoff: datetime | None = None,
        observed_from: datetime | None = None,
        observed_to: datetime | None = None,
    ) -> list[dict[str, Any]]: ...


class _FxService(Protocol):
    def get_historical_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        observed_on: object,
        knowledge_cutoff: datetime | None = None,
    ) -> dict[str, Any]: ...


class RecommendationPortfolioValuationEvidenceService:
    """Build reproducible PIT valuation evidence for user-declared invested positions.

    This service deliberately does not pretend to know broker cash, liabilities or
    unsettled balances. Its scope is the market value of explicitly supplied long
    positions. Every position is bound to canonical instrument identity, one
    explicitly named market-data provider, a market observation already knowable at
    ``as_of`` and, when needed, an FX observation already knowable at the same cutoff.
    Missing or ambiguous evidence fails closed.
    """

    ARTIFACT_VERSION = "athena-portfolio-valuation-evidence-v1"

    def __init__(
        self,
        *,
        instrument_repository: _InstrumentRepository | None = None,
        market_repository: _MarketObservationRepository | None = None,
        fx_service: _FxService | None = None,
    ) -> None:
        self._instrument_repository = instrument_repository or InstrumentRepository()
        self._market_repository = market_repository or MarketObservationRepository()
        self._fx_service = fx_service or FxQuoteService(repository=FxRateRepository())

    def build(
        self,
        *,
        positions: list[dict[str, Any]],
        base_currency: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware_datetime(as_of, "as_of")
        currency = self._currency(base_currency, "base_currency")
        if not isinstance(positions, list):
            raise ValueError("positions debe ser una lista.")

        seen: set[int] = set()
        valued: list[dict[str, Any]] = []
        total = 0.0
        for raw in positions:
            if not isinstance(raw, dict):
                raise ValueError("Cada posición debe ser un objeto.")
            instrument_id = self._positive_int(raw.get("instrumentId"), "instrumentId")
            if instrument_id in seen:
                raise ValueError("La valoración contiene un instrumentId duplicado.")
            seen.add(instrument_id)
            quantity = self._positive_finite(raw.get("quantity"), "quantity")
            position_observed = self._aware_text(
                raw.get("positionObservedAt"), "positionObservedAt"
            )
            position_retrieved = self._aware_text(
                raw.get("positionRetrievedAt"), "positionRetrievedAt"
            )
            if position_observed > position_retrieved:
                raise ValueError("positionObservedAt no puede ser posterior a positionRetrievedAt.")
            if position_retrieved > cutoff:
                raise ValueError("La posición fue conocida después de as_of.")
            position_provider = self._text(
                raw.get("positionSourceProvider"), "positionSourceProvider"
            )
            market_provider = self._text(
                raw.get("marketSourceProvider"), "marketSourceProvider"
            )

            instrument = self._instrument_repository.get_by_id(instrument_id)
            if not isinstance(instrument, dict):
                raise ValueError("La posición referencia un instrumento canónico inexistente.")
            stored_id = self._positive_int(instrument.get("id"), "instrument.id")
            if stored_id != instrument_id:
                raise ValueError("El repositorio devolvió una identidad de instrumento distinta.")
            symbol = self._text(instrument.get("symbol"), "instrument.symbol")
            instrument_currency = self._currency(
                instrument.get("currency"), "instrument.currency"
            )
            canonical_identity = self._canonical_identity(instrument)

            observations = self._market_repository.list_for_instrument(
                instrument_id,
                source_provider=market_provider,
                knowledge_cutoff=cutoff,
            )
            if not isinstance(observations, list) or not observations:
                raise ValueError("Falta precio PIT verificable para una posición.")
            observation = observations[-1]
            if not isinstance(observation, dict):
                raise ValueError("La observación de mercado persistida no es válida.")
            if self._positive_int(observation.get("instrument_id"), "market.instrument_id") != instrument_id:
                raise ValueError("El precio PIT pertenece a otro instrumento.")
            if self._text(observation.get("source_provider"), "market.source_provider") != market_provider:
                raise ValueError("El precio PIT pertenece a otro proveedor.")
            price_observed = self._aware_text(
                observation.get("observed_at"), "market.observed_at"
            )
            price_retrieved = self._aware_text(
                observation.get("retrieved_at"), "market.retrieved_at"
            )
            if price_observed > price_retrieved or price_retrieved > cutoff:
                raise ValueError("El precio PIT viola el corte temporal solicitado.")
            price = self._positive_finite(observation.get("close"), "market.close")
            local_value = quantity * price
            if not math.isfinite(local_value) or local_value <= 0.0:
                raise ValueError("El valor local de posición no es positivo y finito.")

            fx = self._fx_service.get_historical_rate(
                base_currency=instrument_currency,
                quote_currency=currency,
                observed_on=price_observed.date(),
                knowledge_cutoff=cutoff,
            )
            fx_payload = self._validated_fx(
                fx,
                source_currency=instrument_currency,
                base_currency=currency,
                cutoff=cutoff,
                expected_date=price_observed.date().isoformat(),
            )
            base_value = local_value * fx_payload["rate"]
            if not math.isfinite(base_value) or base_value <= 0.0:
                raise ValueError("El valor convertido de posición no es positivo y finito.")
            total += base_value
            if not math.isfinite(total):
                raise ValueError("El agregado de cartera dejó de ser finito.")

            valued.append(
                {
                    "instrumentId": instrument_id,
                    "symbol": symbol,
                    "canonicalIdentity": canonical_identity,
                    "quantity": quantity,
                    "positionSourceProvider": position_provider,
                    "positionObservedAt": position_observed.isoformat(),
                    "positionRetrievedAt": position_retrieved.isoformat(),
                    "instrumentCurrency": instrument_currency,
                    "baseCurrency": currency,
                    "priceField": "close",
                    "price": price,
                    "priceSourceProvider": market_provider,
                    "priceObservedAt": price_observed.isoformat(),
                    "priceRetrievedAt": price_retrieved.isoformat(),
                    "localMarketValue": local_value,
                    "fx": fx_payload,
                    "positionValueInBaseCurrency": base_value,
                }
            )

        valued.sort(key=lambda item: item["instrumentId"])
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "asOf": cutoff.isoformat(),
            "baseCurrency": currency,
            "valuationScope": "invested_long_positions_only_cash_liabilities_unsettled_excluded",
            "cashIncluded": False,
            "liabilitiesIncluded": False,
            "positionCount": len(valued),
            "positions": valued,
            "investedPositionsValueInBaseCurrency": total,
        }
        return {
            "status": "portfolio_valuation_evidence_verified_non_advisory",
            **core,
            "portfolioValuationEvidenceFingerprint": self._fingerprint(core),
            "portfolioValuationEvidenceReady": True,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "automaticTrading": False,
            "policy": {
                "positionsAreCallerDeclaredAndProvenanceLabeled": True,
                "canonicalInstrumentIdentityRequired": True,
                "marketPricePitRequired": True,
                "fxPitRequiredWhenCurrenciesDiffer": True,
                "missingConversionFailsClosed": True,
                "cashMustNotBeInferred": True,
                "brokerNetLiquidationValueNotClaimed": True,
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict) or artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de evidencia de valoración no soportada.")
        if artifact.get("status") != "portfolio_valuation_evidence_verified_non_advisory":
            raise ValueError("La evidencia de valoración no está verificada.")
        if artifact.get("portfolioValuationEvidenceReady") is not True:
            raise ValueError("La evidencia de valoración no está preparada.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La valoración no puede emitir advice.")
        if artifact.get("productionEligible") is not False or artifact.get("automaticTrading") is not False:
            raise ValueError("La valoración no puede habilitar producción/trading.")
        positions = artifact.get("positions")
        if not isinstance(positions, list):
            raise ValueError("La valoración carece de positions.")
        if artifact.get("positionCount") != len(positions):
            raise ValueError("positionCount es inconsistente.")
        seen: set[int] = set()
        recomputed = 0.0
        for position in positions:
            if not isinstance(position, dict):
                raise ValueError("La valoración contiene una posición inválida.")
            instrument_id = self._positive_int(position.get("instrumentId"), "instrumentId")
            if instrument_id in seen:
                raise ValueError("La valoración contiene posiciones duplicadas.")
            seen.add(instrument_id)
            value = self._positive_finite(
                position.get("positionValueInBaseCurrency"),
                "positionValueInBaseCurrency",
            )
            recomputed += value
        supplied_total = self._nonnegative_finite(
            artifact.get("investedPositionsValueInBaseCurrency"),
            "investedPositionsValueInBaseCurrency",
        )
        if not math.isclose(recomputed, supplied_total, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("El total de valoración no coincide con sus posiciones.")
        core_keys = (
            "artifactVersion",
            "asOf",
            "baseCurrency",
            "valuationScope",
            "cashIncluded",
            "liabilitiesIncluded",
            "positionCount",
            "positions",
            "investedPositionsValueInBaseCurrency",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(
            artifact.get("portfolioValuationEvidenceFingerprint"),
            "portfolioValuationEvidenceFingerprint",
        )
        if self._fingerprint(core) != supplied:
            raise ValueError("La evidencia de valoración fue modificada.")
        return artifact

    def _canonical_identity(self, instrument: dict[str, Any]) -> dict[str, Any]:
        required_text = {
            "canonicalInstrumentId": instrument.get("instrument_id"),
            "exchange": instrument.get("exchange_short_name") or instrument.get("exchange"),
            "securityType": instrument.get("instrument_type"),
            "country": instrument.get("country"),
            "currency": instrument.get("currency"),
        }
        normalized = {
            key: self._text(value, f"instrument.{key}")
            for key, value in required_text.items()
        }
        issuer = instrument.get("issuer_id")
        if issuer is None:
            raise ValueError("La identidad canónica carece de issuerId.")
        normalized["issuerId"] = self._positive_int(issuer, "instrument.issuer_id")
        normalized["sector"] = self._text(instrument.get("sector"), "instrument.sector")
        return normalized

    def _validated_fx(
        self,
        payload: object,
        *,
        source_currency: str,
        base_currency: str,
        cutoff: datetime,
        expected_date: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("La conversión FX no devolvió evidencia verificable.")
        if self._currency(payload.get("baseCurrency"), "fx.baseCurrency") != source_currency:
            raise ValueError("La moneda origen FX no coincide con el instrumento.")
        if self._currency(payload.get("quoteCurrency"), "fx.quoteCurrency") != base_currency:
            raise ValueError("La moneda destino FX no coincide con la moneda base.")
        if payload.get("historicalPointInTimeEligible") is not True:
            raise ValueError("La conversión FX no es elegible PIT.")
        rate = self._positive_finite(payload.get("rate"), "fx.rate")
        observed = self._aware_text(payload.get("observedAt"), "fx.observedAt")
        retrieved = self._aware_text(payload.get("retrievedAt"), "fx.retrievedAt")
        if observed > retrieved or observed > cutoff or retrieved > cutoff:
            raise ValueError("La evidencia FX viola el corte PIT.")
        observed_on = str(payload.get("observedOn") or observed.date().isoformat())
        if observed_on != expected_date:
            raise ValueError("La evidencia FX no corresponde a la fecha del precio.")
        provider = self._text(payload.get("sourceProvider"), "fx.sourceProvider")
        source_symbol = payload.get("sourceSymbol")
        if source_currency != base_currency and not str(source_symbol or "").strip():
            raise ValueError("La conversión FX de mercado carece de sourceSymbol.")
        return {
            "rate": rate,
            "sourceProvider": provider,
            "sourceSymbol": source_symbol,
            "observedOn": observed_on,
            "observedAt": observed.isoformat(),
            "retrievedAt": retrieved.isoformat(),
            "historicalPointInTimeEligible": True,
            "replayedFromPersistence": bool(payload.get("replayedFromPersistence")),
        }

    def _currency(self, value: object, field: str) -> str:
        result = str(value or "").strip().upper()
        if len(result) != 3 or not result.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return result

    def _text(self, value: object, field: str) -> str:
        result = str(value or "").strip()
        if not result:
            raise ValueError(f"{field} es obligatorio.")
        return result

    def _positive_int(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    def _positive_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result <= 0.0:
            raise ValueError(f"{field} debe ser positivo.")
        return result

    def _nonnegative_finite(self, value: object, field: str) -> float:
        result = self._finite(value, field)
        if result < 0.0:
            raise ValueError(f"{field} no puede ser negativo.")
        return result

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser finito.")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser finito.") from exc
        if not math.isfinite(result):
            raise ValueError(f"{field} debe ser finito.")
        return result

    def _aware_text(self, value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser fecha ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es una fecha ISO válida.") from exc
        return self._aware_datetime(parsed, field)

    def _aware_datetime(self, value: object, field: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{field} debe ser datetime.")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    def _sha256(self, value: object, field: str) -> str:
        result = str(value or "").strip().lower()
        if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal.")
        return result

    def _fingerprint(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
