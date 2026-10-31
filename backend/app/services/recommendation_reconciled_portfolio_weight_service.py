from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SOURCE_MARKERS = ("financialmodelingprep", "financial modeling prep")


class RecommendationReconciledPortfolioWeightService:
    """Derive diagnostic portfolio weights from persisted reconciled state + PIT valuation.

    This service is intentionally not an optimizer and cannot authorize allocation.
    It only turns independently reconciled cash/quantities and a sealed PIT valuation
    into arithmetic weights. No cash, position quantity, price or FX value is inferred.
    """

    ARTIFACT_VERSION = "reconciled-portfolio-weights-v1"

    def build(
        self,
        *,
        reconciliation_record: dict[str, Any],
        valuation_record: dict[str, Any],
    ) -> dict[str, Any]:
        reconciliation = self._reconciliation_artifact(reconciliation_record)
        valuation = self._valuation_artifact(valuation_record)

        portfolio_id = self._text(reconciliation.get("portfolioId"), "portfolioId")
        reconciliation_key = self._sha256(
            reconciliation.get("reconciliationKey"), "reconciliationKey"
        )
        portfolio_state_key = self._sha256(
            reconciliation.get("portfolioStateKey"), "portfolioStateKey"
        )
        as_of = self._aware_iso(reconciliation.get("asOf"), "reconciliation.asOf")
        currency = self._currency(
            reconciliation.get("reportingCurrency"), "reconciliation.reportingCurrency"
        )
        valuation_as_of = self._aware_iso(valuation.get("asOf"), "valuation.asOf")
        valuation_currency = self._currency(
            valuation.get("baseCurrency"), "valuation.baseCurrency"
        )
        if valuation_as_of != as_of:
            raise ValueError("La valoración PIT debe corresponder exactamente al asOf reconciliado.")
        if valuation_currency != currency:
            raise ValueError("La valoración PIT usa otra moneda; no se permite conversión implícita.")

        snapshot = reconciliation.get("snapshotState")
        if not isinstance(snapshot, dict):
            raise ValueError("La reconciliación persistida carece del snapshotState económico.")
        snapshot_observed = self._aware_iso(snapshot.get("observedAt"), "snapshotState.observedAt")
        snapshot_available = self._aware_iso(snapshot.get("availableAt"), "snapshotState.availableAt")
        if snapshot_observed > snapshot_available or snapshot_available > as_of:
            raise ValueError("snapshotState viola PIT/no-lookahead.")
        snapshot_source = self._text(snapshot.get("source"), "snapshotState.source")
        snapshot_source_ref = self._text(snapshot.get("sourceRef"), "snapshotState.sourceRef")
        self._assert_source_allowed(snapshot_source)
        self._assert_source_allowed(snapshot_source_ref)
        provenance = reconciliation.get("snapshotProvenance")
        if not isinstance(provenance, dict):
            raise ValueError("La reconciliación perdió snapshotProvenance.")
        if self._text(provenance.get("source"), "snapshotProvenance.source") != snapshot_source:
            raise ValueError("snapshotState.source no coincide con snapshotProvenance.")
        if self._text(provenance.get("sourceRef"), "snapshotProvenance.sourceRef") != snapshot_source_ref:
            raise ValueError("snapshotState.sourceRef no coincide con snapshotProvenance.")

        cash_balance = self._nonnegative_finite(snapshot.get("cashBalance"), "snapshotState.cashBalance")
        snapshot_positions = self._snapshot_positions(snapshot.get("positions"))
        valuation_positions = self._valuation_positions(valuation.get("positions"))
        if set(snapshot_positions) != set(valuation_positions):
            missing = sorted(set(snapshot_positions) - set(valuation_positions))
            extra = sorted(set(valuation_positions) - set(snapshot_positions))
            raise ValueError(
                f"Valuation/state identity mismatch; missing={missing}, extra={extra}."
            )

        invested_value = 0.0
        weighted_positions: list[dict[str, Any]] = []
        for instrument_id in sorted(snapshot_positions):
            snapshot_quantity = snapshot_positions[instrument_id]
            valued = valuation_positions[instrument_id]
            if not math.isclose(
                snapshot_quantity,
                float(valued["quantity"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"La cantidad valorada de instrumentId={instrument_id} no coincide con el snapshot reconciliado."
                )
            position_value = self._positive_finite(
                valued["positionValueInBaseCurrency"],
                f"valuation.positions[{instrument_id}].positionValueInBaseCurrency",
            )
            invested_value += position_value
            if not math.isfinite(invested_value):
                raise ValueError("El valor invertido agregado dejó de ser finito.")
            weighted_positions.append(
                {
                    "instrumentId": instrument_id,
                    "symbol": self._text(valued.get("symbol"), "valuation.symbol"),
                    "quantity": snapshot_quantity,
                    "positionValueInReportingCurrency": position_value,
                    "canonicalIdentity": valued.get("canonicalIdentity"),
                    "price": self._positive_finite(valued.get("price"), "valuation.price"),
                    "priceSourceProvider": self._text(
                        valued.get("priceSourceProvider"), "valuation.priceSourceProvider"
                    ),
                    "priceObservedAt": self._aware_iso(
                        valued.get("priceObservedAt"), "valuation.priceObservedAt"
                    ).isoformat(),
                    "priceRetrievedAt": self._aware_iso(
                        valued.get("priceRetrievedAt"), "valuation.priceRetrievedAt"
                    ).isoformat(),
                    "fx": valued.get("fx"),
                }
            )
            self._assert_no_forbidden_sources(valued)

        supplied_invested = self._nonnegative_finite(
            valuation.get("investedPositionsValueInBaseCurrency"),
            "valuation.investedPositionsValueInBaseCurrency",
        )
        if not math.isclose(invested_value, supplied_invested, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("La suma de posiciones no coincide con el total de valoración sellado.")

        total_value = cash_balance + invested_value
        if not math.isfinite(total_value) or total_value <= 0.0:
            raise ValueError("El valor total reconciliado debe ser positivo y finito.")
        cash_weight = cash_balance / total_value
        weight_sum = cash_weight
        for item in weighted_positions:
            weight = float(item["positionValueInReportingCurrency"]) / total_value
            if not math.isfinite(weight) or weight < 0.0 or weight > 1.0:
                raise ValueError("La ponderación derivada no es válida.")
            item["weight"] = weight
            weight_sum += weight
        if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("Las ponderaciones derivadas no reconcilian al 100%.")

        valuation_fingerprint = self._sha256(
            valuation.get("portfolioValuationEvidenceFingerprint"),
            "portfolioValuationEvidenceFingerprint",
        )
        core = {
            "artifactVersion": self.ARTIFACT_VERSION,
            "portfolioId": portfolio_id,
            "asOf": as_of.isoformat(),
            "reportingCurrency": currency,
            "reconciliationKey": reconciliation_key,
            "portfolioStateKey": portfolio_state_key,
            "portfolioValuationEvidenceFingerprint": valuation_fingerprint,
            "cashBalance": cash_balance,
            "cashWeight": cash_weight,
            "investedPositionsValue": invested_value,
            "totalPortfolioValue": total_value,
            "positions": weighted_positions,
            "snapshotProvenance": {
                "observedAt": snapshot_observed.isoformat(),
                "availableAt": snapshot_available.isoformat(),
                "source": snapshot_source,
                "sourceRef": snapshot_source_ref,
            },
        }
        return {
            "module": "reconciled_portfolio_weights",
            "status": "diagnostic_weights_derived_from_reconciled_state_and_pit_valuation",
            **core,
            "weightEvidenceKey": self._fingerprint(core),
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "allocationEligible": False,
            "automaticTrading": False,
            "policy": {
                "weightDerivation": "reconciled_quantities_plus_sealed_pit_valuation_plus_explicit_cash",
                "cash": "from_independent_reconciled_snapshot_never_inferred",
                "prices": "from_sealed_pit_valuation",
                "fx": "from_sealed_pit_valuation_never_implicitly_converted",
                "positionIdentity": "exact_instrument_set_and_quantity_match_required",
                "missingEvidence": "fail_closed",
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "automaticModelMutation": False,
                "allocationAuthority": "not_granted_diagnostic_weights_only",
            },
        }

    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            raise ValueError("Reconciled portfolio weights debe ser un objeto.")
        if artifact.get("module") != "reconciled_portfolio_weights":
            raise ValueError("Reconciled portfolio weights perdió module.")
        if artifact.get("artifactVersion") != self.ARTIFACT_VERSION:
            raise ValueError("Versión de reconciled portfolio weights no soportada.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("Reconciled portfolio weights perdió no_advice.")
        for field in ("productionEligible", "isWeightingReady", "allocationEligible", "automaticTrading"):
            if artifact.get(field) is not False:
                raise ValueError(f"Reconciled portfolio weights intentó habilitar {field}.")
        policy = artifact.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("Reconciled portfolio weights perdió policy.")
        if policy.get("automaticTrading") is not False or policy.get("automaticProductionPromotion") is not False:
            raise ValueError("Reconciled portfolio weights intentó automatización.")
        if policy.get("allocationAuthority") != "not_granted_diagnostic_weights_only":
            raise ValueError("Reconciled portfolio weights sobreafirmó autoridad de allocation.")
        core_keys = (
            "artifactVersion",
            "portfolioId",
            "asOf",
            "reportingCurrency",
            "reconciliationKey",
            "portfolioStateKey",
            "portfolioValuationEvidenceFingerprint",
            "cashBalance",
            "cashWeight",
            "investedPositionsValue",
            "totalPortfolioValue",
            "positions",
            "snapshotProvenance",
        )
        core = {key: artifact.get(key) for key in core_keys}
        supplied = self._sha256(artifact.get("weightEvidenceKey"), "weightEvidenceKey")
        if self._fingerprint(core) != supplied:
            raise ValueError("Reconciled portfolio weights fue modificado tras crear weightEvidenceKey.")
        positions = artifact.get("positions")
        if not isinstance(positions, list):
            raise ValueError("Reconciled portfolio weights perdió positions.")
        cash_weight = self._nonnegative_finite(artifact.get("cashWeight"), "cashWeight")
        total_weight = cash_weight
        seen: set[int] = set()
        for item in positions:
            if not isinstance(item, dict):
                raise ValueError("Reconciled portfolio weights contiene posición inválida.")
            instrument_id = self._positive_int(item.get("instrumentId"), "instrumentId")
            if instrument_id in seen:
                raise ValueError("Reconciled portfolio weights contiene instrumentId duplicado.")
            seen.add(instrument_id)
            total_weight += self._nonnegative_finite(item.get("weight"), "position.weight")
        if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("Reconciled portfolio weights no suma 1.0.")
        return artifact

    def _reconciliation_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict) or not isinstance(record.get("artifact"), dict):
            raise ValueError("Falta reconciliación persistida válida.")
        artifact = record["artifact"]
        if artifact.get("reconciled") is not True:
            raise ValueError("La cartera no está reconciled=true.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La reconciliación perdió no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("isWeightingReady") is not False:
            raise ValueError("La reconciliación intentó habilitar producción/weighting.")
        return artifact

    def _valuation_artifact(self, record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict) or not isinstance(record.get("artifact"), dict):
            raise ValueError("Falta valoración PIT sellada válida.")
        artifact = record["artifact"]
        if artifact.get("portfolioValuationEvidenceReady") is not True:
            raise ValueError("La valoración PIT no está preparada.")
        if artifact.get("advisoryStatus") != "no_advice":
            raise ValueError("La valoración PIT perdió no_advice.")
        if artifact.get("productionEligible") is not False or artifact.get("automaticTrading") is not False:
            raise ValueError("La valoración PIT intentó habilitar producción/trading.")
        if artifact.get("cashIncluded") is not False:
            raise ValueError("La valoración de posiciones no debe mezclar cash inferido.")
        return artifact

    def _snapshot_positions(self, raw: object) -> dict[int, float]:
        if not isinstance(raw, list):
            raise ValueError("snapshotState.positions debe ser una lista.")
        result: dict[int, float] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"snapshotState.positions[{index}] debe ser un objeto.")
            text = self._text(item.get("instrumentId"), f"snapshotState.positions[{index}].instrumentId")
            if not text.isdigit() or str(int(text)) != text or int(text) <= 0:
                raise ValueError("snapshotState instrumentId debe ser identidad canónica entera positiva sin ambigüedad.")
            instrument_id = int(text)
            if instrument_id in result:
                raise ValueError("snapshotState contiene instrumentId duplicado.")
            result[instrument_id] = self._positive_finite(
                item.get("quantity"), f"snapshotState.positions[{index}].quantity"
            )
        return result

    def _valuation_positions(self, raw: object) -> dict[int, dict[str, Any]]:
        if not isinstance(raw, list):
            raise ValueError("valuation.positions debe ser una lista.")
        result: dict[int, dict[str, Any]] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"valuation.positions[{index}] debe ser un objeto.")
            instrument_id = self._positive_int(
                item.get("instrumentId"), f"valuation.positions[{index}].instrumentId"
            )
            if instrument_id in result:
                raise ValueError("valuation.positions contiene instrumentId duplicado.")
            item["quantity"] = self._positive_finite(
                item.get("quantity"), f"valuation.positions[{index}].quantity"
            )
            result[instrument_id] = item
        return result

    def _assert_no_forbidden_sources(self, value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"source", "sourceRef", "sourceProvider", "priceSourceProvider", "positionSourceProvider"} and isinstance(nested, str):
                    self._assert_source_allowed(nested)
                self._assert_no_forbidden_sources(nested)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_sources(nested)

    def _assert_source_allowed(self, value: str) -> None:
        normalized = value.casefold().replace("_", " ").replace("-", " ")
        compact = normalized.replace(" ", "")
        if compact == "fmp" or any(marker in normalized for marker in _FORBIDDEN_SOURCE_MARKERS):
            raise ValueError("FMP/Financial Modeling Prep está prohibido.")

    @staticmethod
    def _text(value: object, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} es obligatorio.")
        return text

    @staticmethod
    def _currency(value: object, field: str) -> str:
        text = str(value or "").strip().upper()
        if len(text) != 3 or not text.isalpha():
            raise ValueError(f"{field} debe ser moneda ISO de tres letras.")
        return text

    @staticmethod
    def _aware_iso(value: object, field: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} debe ser datetime ISO con zona horaria.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} no es datetime ISO válido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return value

    @staticmethod
    def _positive_finite(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico positivo y finito.")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0.0:
            raise ValueError(f"{field} debe ser numérico positivo y finito.")
        return numeric

    @staticmethod
    def _nonnegative_finite(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} debe ser numérico no negativo y finito.")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0:
            raise ValueError(f"{field} debe ser numérico no negativo y finito.")
        return numeric

    @staticmethod
    def _serialize(value: object) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def _fingerprint(cls, value: object) -> str:
        return hashlib.sha256(cls._serialize(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(value: object, field: str) -> str:
        text = str(value or "").strip().lower()
        if _SHA256_RE.fullmatch(text) is None:
            raise ValueError(f"{field} debe ser SHA-256 hexadecimal válido.")
        return text
