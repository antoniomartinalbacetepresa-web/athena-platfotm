from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


class RecommendationResearchOutcomeAttributionService:
    """Bind a posterior realized attribution to the exact frozen research cycle.

    This is an observational research bridge. It does not turn residual return
    into alpha, advice, production eligibility, position sizing or trading.
    """

    def bind(
        self,
        *,
        outcome_id: str,
        cycle_record: dict[str, Any],
        attribution_payload: dict[str, Any],
    ) -> dict[str, Any]:
        outcome_id_normalized = self._text(outcome_id, "outcome_id")
        if not isinstance(cycle_record, dict):
            raise ValueError("cycle_record debe ser un registro persistido válido.")
        package = cycle_record.get("package")
        if not isinstance(package, dict) or not isinstance(package.get("cycle"), dict):
            raise ValueError("cycle_record perdió el package canónico.")
        cycle = package["cycle"]
        integrity = cycle.get("integrity")
        if not isinstance(integrity, dict):
            raise ValueError("El Research Cycle perdió integridad.")
        cycle_hash = self._sha256(integrity.get("cycleHash"), "cycleHash")
        if self._sha256(cycle_record.get("cycle_hash"), "cycle_record.cycle_hash") != cycle_hash:
            raise ValueError("cycle_record no coincide con cycleHash.")

        self._assert_research_only(cycle, "research_cycle")
        if not isinstance(attribution_payload, dict):
            raise ValueError("attribution_payload debe ser un objeto.")
        self._assert_research_only(attribution_payload, "performance_attribution")
        if attribution_payload.get("module") != "performance_attribution":
            raise ValueError("El outcome requiere Performance Attribution canónico.")
        policy = attribution_payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Performance Attribution perdió su política.")
        if policy.get("causalClaim") != "forbidden_arithmetic_attribution_only":
            raise ValueError("El outcome no admite atribución causal no validada.")
        if policy.get("residualInterpretation") != "unexplained_not_automatic_stock_selection_alpha":
            raise ValueError("El residual no puede interpretarse automáticamente como alpha.")
        if policy.get("fx") != "explicit_not_silently_neutralized":
            raise ValueError("El outcome perdió seguridad FX explícita.")

        instrument_id = self._text(cycle.get("instrumentId"), "cycle.instrumentId")
        symbol = self._text(cycle.get("symbol"), "cycle.symbol").upper()
        if self._text(attribution_payload.get("instrumentId"), "attribution.instrumentId") != instrument_id:
            raise ValueError("Performance Attribution no coincide con instrumentId del ciclo.")
        if self._text(attribution_payload.get("symbol"), "attribution.symbol").upper() != symbol:
            raise ValueError("Performance Attribution no coincide con symbol del ciclo.")

        cycle_as_of = self._aware_iso(cycle.get("asOf"), "cycle.asOf")
        outcome_as_of = self._aware_iso(attribution_payload.get("asOf"), "attribution.asOf")
        period_start = self._aware_iso(attribution_payload.get("periodStart"), "attribution.periodStart")
        period_end = self._aware_iso(attribution_payload.get("periodEnd"), "attribution.periodEnd")
        if outcome_as_of <= cycle_as_of:
            raise ValueError("El outcome debe observarse después del asOf congelado del Research Cycle.")
        if period_start < cycle_as_of:
            raise ValueError("El periodo del outcome no puede comenzar antes del Research Cycle congelado.")
        if period_end <= period_start or period_end > outcome_as_of:
            raise ValueError("El periodo del outcome es temporalmente inválido.")

        evidence = attribution_payload.get("evidence")
        if not isinstance(evidence, dict):
            raise ValueError("Performance Attribution perdió provenance.")
        metas: list[tuple[str, dict[str, Any]]] = []
        for key in ("totalReturn", "marketContribution", "fxContribution"):
            meta = evidence.get(key)
            if not isinstance(meta, dict):
                raise ValueError(f"Falta provenance de {key}.")
            metas.append((key, meta))
        factors = evidence.get("factorContributions")
        if not isinstance(factors, dict):
            raise ValueError("Falta provenance de factorContributions.")
        for name, meta in factors.items():
            if not isinstance(meta, dict):
                raise ValueError(f"Provenance inválida para factor {name}.")
            metas.append((f"factorContributions.{name}", meta))

        seen_provenance: set[tuple[str, str]] = set()
        for field, meta in metas:
            available_at = self._aware_iso(meta.get("availableAt"), f"{field}.availableAt")
            if available_at < period_end:
                raise ValueError(f"{field} estaba disponible antes de cerrar el periodo observado.")
            if available_at > outcome_as_of:
                raise ValueError(f"{field} introduce look-ahead respecto al asOf del outcome.")
            source = self._text(meta.get("source"), f"{field}.source")
            source_ref = self._text(meta.get("sourceRef"), f"{field}.sourceRef")
            self._assert_source_allowed(source)
            self._assert_source_allowed(source_ref)
            provenance_key = (source.casefold(), source_ref.casefold())
            if provenance_key in seen_provenance:
                raise ValueError("El outcome contiene provenance duplicada entre componentes.")
            seen_provenance.add(provenance_key)

        for field in (
            "totalReturn",
            "marketContribution",
            "fxContribution",
            "explainedReturn",
            "residualReturn",
        ):
            self._finite(attribution_payload.get(field), field)
        factor_values = attribution_payload.get("factorContributions")
        if not isinstance(factor_values, dict):
            raise ValueError("factorContributions debe ser un objeto.")
        for name, value in factor_values.items():
            self._finite(value, f"factorContributions.{name}")

        canonical = {
            "outcomeId": outcome_id_normalized,
            "cycleHash": cycle_hash,
            "instrumentId": instrument_id,
            "symbol": symbol,
            "cycleAsOf": cycle_as_of.isoformat(),
            "attribution": attribution_payload,
        }
        outcome_hash = self._canonical_hash(canonical)
        return {
            "module": "research_outcome_attribution",
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "outcomeId": outcome_id_normalized,
            "outcomeHash": outcome_hash,
            "cycleHash": cycle_hash,
            "instrumentId": instrument_id,
            "symbol": symbol,
            "cycleAsOf": cycle_as_of.isoformat(),
            "asOf": outcome_as_of.isoformat(),
            "periodStart": period_start.isoformat(),
            "periodEnd": period_end.isoformat(),
            "attribution": attribution_payload,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "posteriorObservation": "period_starts_at_or_after_frozen_cycle_and_evidence_available_after_period_end",
                "causalClaim": "forbidden_arithmetic_attribution_only",
                "residualInterpretation": "unexplained_not_automatic_stock_selection_alpha",
                "learning": "research_only_not_automatic_model_update",
                "fx": "explicit_not_silently_neutralized",
                "integrity": "outcome_hash_binds_cycle_hash_and_exact_attribution_payload",
            },
        }

    def _assert_research_only(self, payload: dict[str, Any], name: str) -> None:
        if payload.get("advisoryStatus") != "no_advice":
            raise ValueError(f"{name} perdió no_advice.")
        if payload.get("productionEligible") is not False:
            raise ValueError(f"{name} intentó habilitar producción.")
        if payload.get("isWeightingReady") is not False:
            raise ValueError(f"{name} intentó habilitar weighting.")
        policy = payload.get("policy")
        if not isinstance(policy, dict):
            raise ValueError(f"{name} perdió policy.")
        if policy.get("automaticTrading") is not False:
            raise ValueError(f"{name} intentó trading automático.")
        if policy.get("automaticProductionPromotion") is not False:
            raise ValueError(f"{name} intentó promoción automática.")

    def _assert_source_allowed(self, value: str) -> None:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido en outcomes.")

    def _canonical_hash(self, payload: object) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _aware_iso(self, value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser fecha ISO válida.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    def _finite(self, value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico.")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field} debe ser finito.")
        return numeric

    def _sha256(self, value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if not _SHA256_RE.fullmatch(text):
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text

    def _text(self, value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text
