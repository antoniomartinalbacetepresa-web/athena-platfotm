from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Mapping, Sequence


@dataclass(frozen=True)
class PortfolioSnapshotPositionEvidence:
    instrument_id: str
    quantity: float


@dataclass(frozen=True)
class PortfolioSnapshotEvidence:
    portfolio_id: str
    reporting_currency: str
    cash_balance: float
    positions: tuple[PortfolioSnapshotPositionEvidence, ...]
    observed_at: datetime
    available_at: datetime
    source: str
    source_ref: str


@dataclass(frozen=True)
class PortfolioStateReconciliationInput:
    reconstructed_state: Mapping[str, object]
    snapshot: PortfolioSnapshotEvidence


@dataclass(frozen=True)
class PortfolioStateReconciliationResult:
    reconciliation_key: str
    portfolio_state_key: str
    portfolio_id: str
    reporting_currency: str
    as_of: datetime
    snapshot_observed_at: datetime
    snapshot_available_at: datetime
    reconciled: bool
    cash_difference: float
    position_mismatches: tuple[Mapping[str, object], ...]
    snapshot_source: str
    snapshot_source_ref: str

    def to_api_dict(self) -> dict[str, object]:
        return {
            "reconciliationKey": self.reconciliation_key,
            "portfolioStateKey": self.portfolio_state_key,
            "portfolioId": self.portfolio_id,
            "reportingCurrency": self.reporting_currency,
            "asOf": self.as_of.isoformat(),
            "snapshotObservedAt": self.snapshot_observed_at.isoformat(),
            "snapshotAvailableAt": self.snapshot_available_at.isoformat(),
            "reconciled": self.reconciled,
            "cashDifference": self.cash_difference,
            "positionMismatches": [dict(item) for item in self.position_mismatches],
            "snapshotProvenance": {
                "source": self.snapshot_source,
                "sourceRef": self.snapshot_source_ref,
            },
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
                "stateMismatchAction": "fail_closed",
                "cashInference": "forbidden",
                "fxInference": "forbidden",
                "snapshotRequired": True,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
        }


class RecommendationPortfolioStateReconciliationService:
    """Reconcile reconstructed portfolio state against independent PIT evidence.

    A hash-consistent event ledger can still omit a real-world event. This service
    therefore compares the reconstructed state with an independently sourced
    snapshot that was available by the requested ``asOf``. Economic mismatches
    are returned as structured evidence and make ``reconciled`` false; malformed,
    late or ambiguous evidence fails closed with ``ValueError``.
    """

    _ABS_TOLERANCE = 1e-9

    def evaluate(
        self,
        *,
        as_of: datetime,
        item: PortfolioStateReconciliationInput,
    ) -> PortfolioStateReconciliationResult:
        as_of_utc = self._aware_utc(as_of, "as_of")
        state = item.reconstructed_state
        snapshot = item.snapshot

        state_key = self._required_text(state.get("portfolioStateKey"), "portfolioStateKey")
        if len(state_key) != 64 or any(char not in "0123456789abcdef" for char in state_key):
            raise ValueError("portfolioStateKey debe ser SHA-256 hexadecimal.")

        portfolio_id = self._required_text(state.get("portfolioId"), "portfolioId")
        reporting_currency = self._currency(state.get("reportingCurrency"), "reportingCurrency")
        state_as_of = self._parse_datetime(state.get("asOf"), "state.asOf")
        if state_as_of != as_of_utc:
            raise ValueError("El estado reconstruido debe corresponder exactamente al as_of reconciliado.")

        if snapshot.portfolio_id.strip() != portfolio_id:
            raise ValueError("El snapshot pertenece a otra cartera.")
        snapshot_currency = self._currency(snapshot.reporting_currency, "snapshot.reporting_currency")
        if snapshot_currency != reporting_currency:
            raise ValueError("Moneda del snapshot incompatible; se requiere evidencia FX explícita.")

        observed_at = self._aware_utc(snapshot.observed_at, "snapshot.observed_at")
        available_at = self._aware_utc(snapshot.available_at, "snapshot.available_at")
        if observed_at > available_at:
            raise ValueError("snapshot.observed_at no puede ser posterior a snapshot.available_at.")
        if available_at > as_of_utc:
            raise ValueError("El snapshot no estaba disponible en el as_of solicitado.")

        source = self._required_text(snapshot.source, "snapshot.source")
        source_ref = self._required_text(snapshot.source_ref, "snapshot.source_ref")
        snapshot_cash = self._finite(snapshot.cash_balance, "snapshot.cash_balance")
        reconstructed_cash = self._finite(state.get("cashBalance"), "state.cashBalance")

        reconstructed_positions = self._positions_from_state(state.get("positions"))
        snapshot_positions = self._positions_from_snapshot(snapshot.positions)

        cash_difference = snapshot_cash - reconstructed_cash
        if math.isclose(cash_difference, 0.0, rel_tol=0.0, abs_tol=self._ABS_TOLERANCE):
            cash_difference = 0.0

        mismatches: list[dict[str, object]] = []
        for instrument_id in sorted(set(reconstructed_positions) | set(snapshot_positions)):
            reconstructed_quantity = reconstructed_positions.get(instrument_id, 0.0)
            snapshot_quantity = snapshot_positions.get(instrument_id, 0.0)
            difference = snapshot_quantity - reconstructed_quantity
            if math.isclose(difference, 0.0, rel_tol=0.0, abs_tol=self._ABS_TOLERANCE):
                continue
            mismatches.append(
                {
                    "instrumentId": instrument_id,
                    "reconstructedQuantity": reconstructed_quantity,
                    "snapshotQuantity": snapshot_quantity,
                    "difference": difference,
                    "classification": (
                        "missing_from_ledger_state"
                        if reconstructed_quantity == 0.0
                        else "unexpected_in_ledger_state"
                        if snapshot_quantity == 0.0
                        else "quantity_mismatch"
                    ),
                }
            )

        reconciled = cash_difference == 0.0 and not mismatches
        identity_payload = {
            "portfolioStateKey": state_key,
            "portfolioId": portfolio_id,
            "reportingCurrency": reporting_currency,
            "asOf": as_of_utc.isoformat(),
            "snapshot": {
                "cashBalance": format(snapshot_cash, ".17g"),
                "positions": [
                    {
                        "instrumentId": instrument_id,
                        "quantity": format(quantity, ".17g"),
                    }
                    for instrument_id, quantity in sorted(snapshot_positions.items())
                ],
                "observedAt": observed_at.isoformat(),
                "availableAt": available_at.isoformat(),
                "source": source,
                "sourceRef": source_ref,
            },
            "cashDifference": format(cash_difference, ".17g"),
            "positionMismatches": mismatches,
        }
        reconciliation_key = hashlib.sha256(
            json.dumps(
                identity_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        return PortfolioStateReconciliationResult(
            reconciliation_key=reconciliation_key,
            portfolio_state_key=state_key,
            portfolio_id=portfolio_id,
            reporting_currency=reporting_currency,
            as_of=as_of_utc,
            snapshot_observed_at=observed_at,
            snapshot_available_at=available_at,
            reconciled=reconciled,
            cash_difference=cash_difference,
            position_mismatches=tuple(mismatches),
            snapshot_source=source,
            snapshot_source_ref=source_ref,
        )

    def _positions_from_state(self, raw: object) -> dict[str, float]:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("state.positions debe ser una lista de posiciones.")
        positions: dict[str, float] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise ValueError(f"state.positions[{index}] debe ser un objeto.")
            instrument_id = self._required_text(
                item.get("instrumentId"),
                f"state.positions[{index}].instrumentId",
            )
            if instrument_id in positions:
                raise ValueError("El estado reconstruido contiene instrumentos duplicados.")
            positions[instrument_id] = self._finite(
                item.get("quantity"),
                f"state.positions[{index}].quantity",
            )
        return positions

    def _positions_from_snapshot(
        self,
        raw: tuple[PortfolioSnapshotPositionEvidence, ...],
    ) -> dict[str, float]:
        positions: dict[str, float] = {}
        for index, item in enumerate(raw):
            instrument_id = self._required_text(
                item.instrument_id,
                f"snapshot.positions[{index}].instrument_id",
            )
            if instrument_id in positions:
                raise ValueError("El snapshot contiene instrumentos duplicados.")
            positions[instrument_id] = self._finite(
                item.quantity,
                f"snapshot.positions[{index}].quantity",
            )
        return positions

    @staticmethod
    def _required_text(raw: object, field: str) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} es obligatorio.")
        return raw.strip()

    @classmethod
    def _currency(cls, raw: object, field: str) -> str:
        value = cls._required_text(raw, field).upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError(f"{field} debe ser una moneda ISO de tres letras.")
        return value

    @staticmethod
    def _finite(raw: object, field: str) -> float:
        if isinstance(raw, bool):
            raise ValueError(f"{field} debe ser numérico y finito.")
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} debe ser numérico y finito.") from exc
        if not math.isfinite(value):
            raise ValueError(f"{field} debe ser numérico y finito.")
        return value

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _parse_datetime(cls, raw: object, field: str) -> datetime:
        if isinstance(raw, datetime):
            return cls._aware_utc(raw, field)
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} debe ser un timestamp ISO con zona horaria.")
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} debe ser un timestamp ISO válido.") from exc
        return cls._aware_utc(value, field)
