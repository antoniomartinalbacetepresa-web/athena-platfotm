from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.recommendation_dividend_signal_service import RecommendationDividendSignalService


class _DividendSignalService(Protocol):
    def evaluate(self, *, symbol: str, as_of: datetime, sustainability_provider: str | None = None) -> object: ...


@dataclass(frozen=True)
class RecommendationDividendEvidenceContract:
    signal: dict[str, Any]
    knowledge_cutoff: str
    production_eligible: bool = False

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "knowledgeCutoff": self.knowledge_cutoff,
            "productionEligible": self.production_eligible,
            "automaticTrading": False,
            "policy": {
                "requiredDividendDimensions": [
                    "frequency",
                    "trailingYield",
                    "dividendGrowthRate",
                    "paymentStabilityScore",
                    "earningsPayoutRatio",
                    "fcfPayoutRatio",
                    "financialPeriodSustainability",
                    "totalReturn60d",
                ],
                "pit": "market_dividend_and_sustainability_evidence_must_share_the_explicit_knowledge_cutoff",
                "authority": "diagnostic_only_no_automatic_weighting_learning_promotion_or_trading",
            },
        }


class RecommendationDividendEvidenceContractService:
    """Fail-closed canonical contract for dividend evidence used by recommendations."""

    _ALLOWED_FREQUENCIES = {
        "none",
        "insufficient_history",
        "monthly",
        "quarterly",
        "semiannual",
        "annual",
        "irregular",
    }

    def __init__(self, *, signal_service: _DividendSignalService | None = None) -> None:
        self._signal_service = signal_service or RecommendationDividendSignalService()

    def evaluate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        sustainability_provider: str | None = None,
    ) -> RecommendationDividendEvidenceContract:
        cutoff = self._aware_utc(as_of)
        result = self._signal_service.evaluate(
            symbol=symbol,
            as_of=cutoff,
            sustainability_provider=sustainability_provider,
        )
        to_api_dict = getattr(result, "to_api_dict", None)
        if not callable(to_api_dict):
            raise RuntimeError("La señal de dividendos no respeta el contrato canónico.")
        signal = to_api_dict()
        if not isinstance(signal, dict) or signal.get("productionEligible") is not False:
            raise RuntimeError("La señal de dividendos intentó elevar autoridad de producción.")
        signal_cutoff = self._parse_aware(signal.get("asOf"), "asOf")
        if signal_cutoff != cutoff:
            raise RuntimeError("La señal de dividendos usó otro corte point-in-time.")

        dividend = signal.get("dividend")
        if dividend is not None:
            if not isinstance(dividend, dict) or dividend.get("pitSafe") is not True:
                raise RuntimeError("La evidencia de dividendos no es PIT-safe.")
            dividend_cutoff = self._parse_aware(dividend.get("knowledgeCutoff"), "dividend.knowledgeCutoff")
            if dividend_cutoff != cutoff:
                raise RuntimeError("La evidencia de dividendos usó otro knowledge_cutoff.")
            for field in ("frequency", "trailingYield", "dividendGrowthRate", "paymentStabilityScore"):
                if field not in dividend:
                    raise RuntimeError(f"La evidencia de dividendos no expone {field}.")
            frequency = dividend.get("frequency")
            if frequency not in self._ALLOWED_FREQUENCIES:
                raise RuntimeError("La frecuencia de dividendos no pertenece al contrato canónico.")
            self._optional_ratio(dividend.get("trailingYield"), "dividend.trailingYield", minimum=0.0)
            self._optional_ratio(dividend.get("dividendGrowthRate"), "dividend.dividendGrowthRate")
            self._optional_ratio(dividend.get("paymentStabilityScore"), "dividend.paymentStabilityScore", minimum=0.0, maximum=1.0)

        sustainability = signal.get("financialPeriodSustainability")
        if sustainability is not None:
            if not isinstance(sustainability, dict):
                raise RuntimeError("La sostenibilidad de dividendos tiene formato inválido.")
            if sustainability.get("pitSafe") is not True:
                raise RuntimeError("La sostenibilidad de dividendos no es PIT-safe.")
            sustainability_cutoff = self._parse_aware(
                sustainability.get("knowledgeCutoff"),
                "financialPeriodSustainability.knowledgeCutoff",
            )
            if sustainability_cutoff != cutoff:
                raise RuntimeError("La sostenibilidad de dividendos usó otro knowledge_cutoff.")
            provider = sustainability.get("sourceProvider")
            if not isinstance(provider, str) or not provider.strip():
                raise RuntimeError("La sostenibilidad de dividendos carece de provenance de proveedor.")
            self._optional_ratio(sustainability.get("sustainabilityScore"), "financialPeriodSustainability.sustainabilityScore", minimum=0.0, maximum=1.0)

        for field in ("totalReturn60d", "earningsPayoutRatio", "fcfPayoutRatio", "financialPeriodSustainability"):
            if field not in signal:
                raise RuntimeError(f"La señal canónica no expone {field}.")
        self._optional_ratio(signal.get("totalReturn60d"), "totalReturn60d")
        self._optional_ratio(signal.get("earningsPayoutRatio"), "earningsPayoutRatio", minimum=0.0)
        self._optional_ratio(signal.get("fcfPayoutRatio"), "fcfPayoutRatio", minimum=0.0)

        return RecommendationDividendEvidenceContract(signal=signal, knowledge_cutoff=cutoff.isoformat())

    @staticmethod
    def _optional_ratio(value: object, field: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"{field} debe ser numérico cuando existe.")
        numeric = float(value)
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise RuntimeError(f"{field} debe ser finito.")
        if minimum is not None and numeric < minimum:
            raise RuntimeError(f"{field} está por debajo del mínimo permitido.")
        if maximum is not None and numeric > maximum:
            raise RuntimeError(f"{field} supera el máximo permitido.")

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_aware(value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError(f"{field} es inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)
