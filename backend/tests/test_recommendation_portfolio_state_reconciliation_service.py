from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from app.services.recommendation_portfolio_state_reconciliation_service import (
    PortfolioSnapshotEvidence,
    PortfolioSnapshotPositionEvidence,
    PortfolioStateReconciliationInput,
    RecommendationPortfolioStateReconciliationService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _state(
    *,
    cash: float = 60.0,
    positions: list[dict[str, object]] | None = None,
    currency: str = "EUR",
) -> dict[str, object]:
    return {
        "portfolioStateKey": "a" * 64,
        "portfolioId": "portfolio-1",
        "reportingCurrency": currency,
        "asOf": AS_OF.isoformat(),
        "cashBalance": cash,
        "positions": positions
        if positions is not None
        else [
            {"instrumentId": "FIGI:AAA", "quantity": 2.0},
            {"instrumentId": "FIGI:BBB", "quantity": 3.0},
        ],
    }


def _snapshot(
    *,
    cash: float = 60.0,
    positions: tuple[PortfolioSnapshotPositionEvidence, ...] | None = None,
    currency: str = "EUR",
    available_at: datetime | None = None,
) -> PortfolioSnapshotEvidence:
    return PortfolioSnapshotEvidence(
        portfolio_id="portfolio-1",
        reporting_currency=currency,
        cash_balance=cash,
        positions=positions
        if positions is not None
        else (
            PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),
            PortfolioSnapshotPositionEvidence("FIGI:BBB", 3.0),
        ),
        observed_at=AS_OF - timedelta(minutes=10),
        available_at=available_at or AS_OF - timedelta(minutes=5),
        source="broker_snapshot",
        source_ref="snapshot-2026-09-08T1150Z",
    )


def _evaluate(
    *,
    state: dict[str, object] | None = None,
    snapshot: PortfolioSnapshotEvidence | None = None,
):
    return RecommendationPortfolioStateReconciliationService().evaluate(
        as_of=AS_OF,
        item=PortfolioStateReconciliationInput(
            reconstructed_state=state or _state(),
            snapshot=snapshot or _snapshot(),
        ),
    )


def test_reconciles_exact_independent_snapshot_and_preserves_safety_policy() -> None:
    result = _evaluate()

    assert result.reconciled is True
    assert result.cash_difference == 0.0
    assert result.position_mismatches == ()
    assert len(result.reconciliation_key) == 64
    assert set(result.reconciliation_key) <= set("0123456789abcdef")

    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["stateMismatchAction"] == "fail_closed"
    assert payload["policy"]["cashInference"] == "forbidden"
    assert payload["policy"]["fxInference"] == "forbidden"
    assert payload["snapshotProvenance"] == {
        "source": "broker_snapshot",
        "sourceRef": "snapshot-2026-09-08T1150Z",
    }


def test_cash_mismatch_is_economic_evidence_not_silently_corrected() -> None:
    result = _evaluate(snapshot=_snapshot(cash=61.5))

    assert result.reconciled is False
    assert result.cash_difference == pytest.approx(1.5)
    assert result.position_mismatches == ()


def test_missing_position_is_classified_and_blocks_reconciliation() -> None:
    result = _evaluate(
        snapshot=_snapshot(
            positions=(PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),),
        )
    )

    assert result.reconciled is False
    assert result.position_mismatches == (
        {
            "instrumentId": "FIGI:BBB",
            "reconstructedQuantity": 3.0,
            "snapshotQuantity": 0.0,
            "difference": -3.0,
            "classification": "unexpected_in_ledger_state",
        },
    )


def test_position_present_only_in_snapshot_is_missing_from_ledger_state() -> None:
    result = _evaluate(
        snapshot=_snapshot(
            positions=(
                PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),
                PortfolioSnapshotPositionEvidence("FIGI:BBB", 3.0),
                PortfolioSnapshotPositionEvidence("FIGI:CCC", 1.0),
            ),
        )
    )

    assert result.reconciled is False
    assert result.position_mismatches[-1]["instrumentId"] == "FIGI:CCC"
    assert result.position_mismatches[-1]["classification"] == "missing_from_ledger_state"


def test_quantity_mismatch_is_reported_without_alpha_or_weighting_semantics() -> None:
    result = _evaluate(
        snapshot=_snapshot(
            positions=(
                PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.5),
                PortfolioSnapshotPositionEvidence("FIGI:BBB", 3.0),
            ),
        )
    )

    assert result.reconciled is False
    mismatch = result.position_mismatches[0]
    assert mismatch["classification"] == "quantity_mismatch"
    assert mismatch["difference"] == pytest.approx(0.5)
    assert result.to_api_dict()["isWeightingReady"] is False


def test_snapshot_available_after_as_of_is_rejected_for_no_lookahead() -> None:
    with pytest.raises(ValueError, match="no estaba disponible"):
        _evaluate(snapshot=_snapshot(available_at=AS_OF + timedelta(seconds=1)))


def test_snapshot_observed_after_available_is_rejected() -> None:
    snapshot = PortfolioSnapshotEvidence(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        cash_balance=60.0,
        positions=(),
        observed_at=AS_OF,
        available_at=AS_OF - timedelta(seconds=1),
        source="broker_snapshot",
        source_ref="bad-order",
    )
    with pytest.raises(ValueError, match="observed_at"):
        _evaluate(snapshot=snapshot)


def test_naive_snapshot_timestamp_is_rejected() -> None:
    snapshot = PortfolioSnapshotEvidence(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        cash_balance=60.0,
        positions=(),
        observed_at=datetime(2026, 9, 8, 11, 50),
        available_at=AS_OF - timedelta(minutes=5),
        source="broker_snapshot",
        source_ref="naive-time",
    )
    with pytest.raises(ValueError, match="zona horaria"):
        _evaluate(snapshot=snapshot)


def test_currency_mismatch_fails_closed_instead_of_inferring_fx() -> None:
    with pytest.raises(ValueError, match="evidencia FX explícita"):
        _evaluate(snapshot=_snapshot(currency="USD"))


def test_non_finite_cash_is_rejected() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finito"):
            _evaluate(snapshot=_snapshot(cash=value))


def test_duplicate_snapshot_instrument_identity_is_rejected() -> None:
    snapshot = _snapshot(
        positions=(
            PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),
            PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),
        )
    )
    with pytest.raises(ValueError, match="duplicados"):
        _evaluate(snapshot=snapshot)


def test_duplicate_reconstructed_instrument_identity_is_rejected() -> None:
    state = _state(
        positions=[
            {"instrumentId": "FIGI:AAA", "quantity": 2.0},
            {"instrumentId": "FIGI:AAA", "quantity": 2.0},
        ]
    )
    with pytest.raises(ValueError, match="duplicados"):
        _evaluate(state=state)


def test_reconciliation_identity_is_independent_of_snapshot_position_order() -> None:
    first = _evaluate()
    second = _evaluate(
        snapshot=_snapshot(
            positions=(
                PortfolioSnapshotPositionEvidence("FIGI:BBB", 3.0),
                PortfolioSnapshotPositionEvidence("FIGI:AAA", 2.0),
            )
        )
    )

    assert first.reconciliation_key == second.reconciliation_key


def test_provenance_change_changes_reconciliation_identity() -> None:
    first = _evaluate()
    changed_snapshot = PortfolioSnapshotEvidence(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        cash_balance=60.0,
        positions=_snapshot().positions,
        observed_at=AS_OF - timedelta(minutes=10),
        available_at=AS_OF - timedelta(minutes=5),
        source="broker_snapshot",
        source_ref="different-snapshot-reference",
    )
    second = _evaluate(snapshot=changed_snapshot)

    assert first.reconciliation_key != second.reconciliation_key


def test_invalid_portfolio_state_key_is_rejected() -> None:
    state = _state()
    state["portfolioStateKey"] = "not-a-sha"
    with pytest.raises(ValueError, match="SHA-256"):
        _evaluate(state=state)


def test_state_as_of_must_match_reconciliation_as_of_exactly() -> None:
    state = _state()
    state["asOf"] = (AS_OF - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="exactamente"):
        _evaluate(state=state)
