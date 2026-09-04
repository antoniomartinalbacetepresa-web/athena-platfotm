from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository


@dataclass(frozen=True)
class PortfolioInstrumentIdentity:
    database_instrument_id: int
    canonical_instrument_id: str
    issuer_id: str
    symbol: str
    company_name: str
    exchange: str | None
    exchange_short_name: str | None
    instrument_type: str
    country: str | None
    currency: str
    sector: str | None
    source_provider: str
    retrieved_at: str
    resolution_method: str
    exchange_verified: bool

    @property
    def is_risk_ready(self) -> bool:
        return self.exchange_verified

    @property
    def is_weighting_ready(self) -> bool:
        # Resolving one portfolio listing does not prove issuer-domicile or
        # deduplication coverage for global weighting.
        return False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "databaseInstrumentId": self.database_instrument_id,
            "canonicalInstrumentId": self.canonical_instrument_id,
            "issuerId": self.issuer_id,
            "symbol": self.symbol,
            "companyName": self.company_name,
            "exchange": self.exchange,
            "exchangeShortName": self.exchange_short_name,
            "instrumentType": self.instrument_type,
            "country": self.country,
            "currency": self.currency,
            "sector": self.sector,
            "sourceProvider": self.source_provider,
            "retrievedAt": self.retrieved_at,
            "resolutionMethod": self.resolution_method,
            "exchangeVerified": self.exchange_verified,
            "isRiskReady": self.is_risk_ready,
            "isWeightingReady": self.is_weighting_ready,
            "recommendationPolicy": "no_advice",
            "productionEligible": False,
            "automaticTrading": False,
        }


class PortfolioInstrumentIdentityService:
    """Resolves a portfolio listing against ATHENA's persisted canonical catalog.

    Resolution is deterministic and fail-closed. A unique symbol may identify a
    catalog row for diagnostics, but risk readiness additionally requires that a
    supplied exchange matches either the canonical full or short exchange code.
    No fuzzy issuer, symbol or exchange matching is performed.
    """

    def __init__(
        self,
        *,
        database: AthenaDatabase | None = None,
        repository: InstrumentRepository | None = None,
    ) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = (
            repository
            if repository is not None
            else InstrumentRepository(database=self._database)
        )

    def resolve(
        self,
        *,
        symbol: str,
        exchange: str | None,
    ) -> PortfolioInstrumentIdentity:
        normalized_symbol = self._required_upper(symbol, "symbol")
        normalized_exchange = self._optional_upper(exchange)

        candidates = [
            row
            for row in self._repository.list_active()
            if str(row.get("symbol") or "").strip().upper() == normalized_symbol
        ]
        if not candidates:
            raise ValueError(
                "El instrumento no existe como listing activo en el catálogo canónico."
            )

        exact_candidates: list[dict[str, Any]] = []
        if normalized_exchange is not None:
            exact_candidates = [
                row
                for row in candidates
                if normalized_exchange
                in {
                    self._optional_upper(row.get("exchange")),
                    self._optional_upper(row.get("exchange_short_name")),
                }
            ]

        if len(exact_candidates) > 1:
            raise ValueError(
                "La identidad sigue siendo ambigua aun con el exchange proporcionado."
            )

        if len(exact_candidates) == 1:
            selected = exact_candidates[0]
            method = "symbol_and_exchange_exact"
            exchange_verified = True
        else:
            if len(candidates) != 1:
                raise ValueError(
                    "El símbolo corresponde a múltiples listings activos; se requiere un exchange canónico exacto."
                )
            selected = candidates[0]
            method = "unique_active_symbol"
            exchange_verified = normalized_exchange is None

        return self._validate_selected(
            selected,
            resolution_method=method,
            exchange_verified=exchange_verified,
        )

    def _validate_selected(
        self,
        row: dict[str, Any],
        *,
        resolution_method: str,
        exchange_verified: bool,
    ) -> PortfolioInstrumentIdentity:
        database_id_raw = row.get("id")
        if isinstance(database_id_raw, bool):
            raise ValueError("La clave interna del instrumento es inválida.")
        try:
            database_id = int(database_id_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("La clave interna del instrumento es inválida.") from exc
        if database_id <= 0:
            raise ValueError("La clave interna del instrumento es inválida.")

        canonical_id = self._required_text(
            row.get("instrument_id"), "instrument_id"
        )
        issuer_id = self._required_text(row.get("issuer_id"), "issuer_id")
        symbol = self._required_upper(row.get("symbol"), "symbol")
        company_name = self._required_text(row.get("company_name"), "company_name")
        instrument_type = self._required_text(
            row.get("instrument_type"), "instrument_type"
        )
        currency = self._required_upper(row.get("currency"), "currency")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("La moneda canónica del instrumento no es ISO válida.")
        source_provider = self._required_text(
            row.get("source_provider"), "source_provider"
        )
        retrieved_at = self._required_text(row.get("retrieved_at"), "retrieved_at")

        if int(row.get("is_active") or 0) != 1:
            raise ValueError("La listing seleccionada no está activa.")

        return PortfolioInstrumentIdentity(
            database_instrument_id=database_id,
            canonical_instrument_id=canonical_id,
            issuer_id=issuer_id,
            symbol=symbol,
            company_name=company_name,
            exchange=self._optional_text(row.get("exchange")),
            exchange_short_name=self._optional_text(row.get("exchange_short_name")),
            instrument_type=instrument_type,
            country=self._optional_text(row.get("country")),
            currency=currency,
            sector=self._optional_text(row.get("sector")),
            source_provider=source_provider,
            retrieved_at=retrieved_at,
            resolution_method=resolution_method,
            exchange_verified=exchange_verified,
        )

    def _required_text(self, value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio para identidad canónica.")
        return text

    def _required_upper(self, value: Any, field: str) -> str:
        return self._required_text(value, field).upper()

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _optional_upper(self, value: Any) -> str | None:
        text = self._optional_text(value)
        return text.upper() if text is not None else None
