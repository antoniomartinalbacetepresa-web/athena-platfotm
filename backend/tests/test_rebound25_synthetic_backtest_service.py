"""Synthetic-only prior-25-session rebound research, never actual orders."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.services.rebound25_synthetic_backtest_service import (
    Rebound25Parameters, SyntheticReboundBar, run_rebound25_synthetic_backtest,
)


def parameters(**changes):
    return replace(Rebound25Parameters(
        take_profit_pct=3, stop_loss_pct=2, max_holding_sessions=5,
        commission_bps=5, spread_bps=10, slippage_bps=5,
        order_units=10, min_average_volume=100, max_volume_participation=.01,
        min_relative_volume=1.5,
    ), **changes)


def synthetic_bars():
    first = datetime(2026, 1, 1, 14, tzinfo=timezone.utc)
    bars = [SyntheticReboundBar(
        session=(first + timedelta(days=index)).date(),
        open_at=first + timedelta(days=index),
        observed_at=first + timedelta(days=index, hours=7),
        available_at=first + timedelta(days=index, hours=7, minutes=1),
        open=100, high=102, low=99, close=100, volume=1000,
    ) for index in range(28)]
    bars[25] = replace(bars[25], low=97, close=98, volume=2000)
    # A later closing rebound must be confirmed before entry.
    bars[26] = replace(bars[26], open=98, high=100, low=97, close=99.5, volume=2000)
    # Entry-day final volume is future information and cannot fit the decision.
    bars[27] = replace(bars[27], open=99.5, high=104, low=98, close=102, volume=1)
    return bars


def run(bars=None, protocol=None, **changes):
    selected = bars if bars is not None else synthetic_bars()
    args = dict(
        parameters=protocol or parameters(),
        expected_sessions=[bar.session for bar in selected],
        as_of=max(bar.available_at for bar in selected),
        precommitted_at=selected[0].open_at,
        instrument_id="SYNTH:XTEST", currency="USD", evidence_kind="synthetic_fixture",
    )
    return run_rebound25_synthetic_backtest(selected, **(args | changes))


def test_prior_25_low_rebound_is_reproducible_costed_and_never_production():
    result = run()
    assert result == run()
    assert len(result["parameterFingerprint"]) == len(result["inputFingerprint"]) == 64
    assert len(result["resultFingerprint"]) == 64
    assert result["parameters"]["lookback_sessions"] == 25
    assert result["signals"][0]["priorLow"] == 99
    assert result["signals"][0]["referenceSessionCount"] == 25
    assert result["signals"][0]["relativeVolume"] == 2
    assert result["signals"][0]["outcome"] == "next_open_simulated_entry"
    trade = result["trades"][0]
    assert trade["signalSession"] == "2026-01-26"
    assert trade["confirmationSession"] == "2026-01-27"
    assert trade["entrySession"] == trade["exitSession"] == "2026-01-28"
    assert datetime.fromisoformat(trade["breachDecisionAt"]) < datetime.fromisoformat(trade["confirmationDecisionAt"])
    assert datetime.fromisoformat(trade["decisionAt"]) < datetime.fromisoformat(trade["entryAt"])
    assert trade["entryPrice"] == pytest.approx(99.5 * 1.001)
    assert trade["exitPrice"] == pytest.approx(99.5 * 1.03 * .999)
    assert trade["grossPnl"] == pytest.approx(29.85)
    assert trade["commissionCost"] == pytest.approx((trade["entryPrice"] + trade["exitPrice"]) * 10 * .0005)
    assert trade["netPnl"] == pytest.approx(trade["grossPnl"] - trade["spreadAndSlippageCost"] - trade["commissionCost"])
    assert result["closedTradeCount"] == 1
    assert result["totalNetPnl"] == trade["netPnl"]
    assert result["openPosition"] is None
    assert result["evidenceKind"] == "synthetic_fixture"
    for flag in ("productionEligible", "historicalPointInTimeEligible", "outOfSampleValidated",
                 "automaticTrading", "ordersEnabled"):
        assert result[flag] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["warnings"]


def test_exactly_25_prior_lows_are_used_not_24_or_current_low():
    bars = synthetic_bars()
    # The oldest of the 25 prior sessions must not disappear from the minimum.
    bars[0] = replace(bars[0], low=90)
    assert run(bars)["signals"] == []
    assert run()["signals"][0]["priorLow"] == 99  # current low 97 is excluded


def test_close_equal_to_prior_low_is_not_a_breach():
    bars = synthetic_bars()
    bars[25] = replace(bars[25], close=99)
    assert run(bars)["signals"] == []


def test_breach_without_later_confirmed_rebound_never_enters():
    bars = synthetic_bars()
    bars[26] = replace(bars[26], close=98.5)
    bars[27] = replace(bars[27], open=98.5, close=98.5)
    result = run(bars)
    assert result["trades"] == []
    assert result["openPosition"] is None
    assert result["signals"][0]["outcome"] == "rebound_confirmation_unavailable_at_end"
    assert result["pendingHypothesis"]["breachSession"] == bars[25].session.isoformat()


def test_confirmation_threshold_is_strict_and_is_a_versioned_parameter():
    bars = synthetic_bars()[:27]
    bars[26] = replace(bars[26], close=98 * 1.01)
    result = run(bars)
    assert result["signals"][0].get("confirmationSession") is None
    assert result["trades"] == []
    assert run(protocol=parameters(min_rebound_pct=5))["trades"] == []
    assert run(protocol=parameters(min_rebound_pct=5))["parameterFingerprint"] != run()["parameterFingerprint"]


def test_confirmation_window_expires_without_reentering_a_later_rebound():
    bars = synthetic_bars()
    bars[26] = replace(bars[26], close=98.5)
    result = run(bars, protocol=parameters(max_confirmation_sessions=1))
    assert result["trades"] == []
    assert result["signals"][0]["outcome"] == "rebound_confirmation_expired"
    assert result["abstentions"][0]["reason"] == "rebound_confirmation_expired"


def test_confirmation_does_not_modify_the_prior_25_session_breach_baseline():
    bars = synthetic_bars()
    # A low in the confirmation session is not retroactively a reference low.
    bars[26] = replace(bars[26], low=50)
    result = run(bars)
    assert result["signals"][0]["priorLow"] == 99
    assert result["signals"][0]["referenceSessionCount"] == 25
    assert result["trades"][0]["entrySession"] == bars[27].session.isoformat()


def test_confirmation_volume_must_support_the_known_entry_participation_proxy():
    bars = synthetic_bars()
    bars[26] = replace(bars[26], volume=1)
    result = run(bars)
    assert result["trades"] == []
    assert result["signals"][0]["outcome"] == "confirmation_volume_or_participation_filter"


def test_entry_never_uses_confirmation_close_or_open_before_confirmation_availability():
    bars = synthetic_bars()
    bars[26] = replace(bars[26], available_at=bars[27].open_at + timedelta(seconds=1))
    result = run(bars)
    assert result["signals"][0]["outcome"] == "confirmation_not_available_before_next_open"
    assert result["trades"] == []
    assert result["openPosition"] is None


def test_future_available_reference_evidence_causes_an_explicit_abstention():
    bars = synthetic_bars()
    bars[5] = replace(bars[5], available_at=bars[27].available_at)
    result = run(bars)
    assert result["trades"] == []
    assert result["abstentions"][0] == {
        "session": bars[25].session.isoformat(), "reason": "prior_evidence_not_yet_available",
    }


def test_unavailable_next_session_cannot_be_fabricated():
    result = run(synthetic_bars()[:27])
    assert result["signals"][0]["outcome"] == "next_session_unavailable"
    assert result["trades"] == []


@pytest.mark.parametrize("change", [
    {"min_relative_volume": 2.01}, {"min_average_volume": 1001},
    {"order_units": 21},
])
def test_volume_and_known_participation_limits_gate_entry(change):
    result = run(protocol=parameters(**change))
    assert result["signals"][0]["outcome"] == "volume_or_participation_filter"
    assert result["trades"] == []


def test_zero_reference_volume_is_not_divided_or_treated_as_liquid():
    bars = synthetic_bars()
    bars[:25] = [replace(bar, volume=0) for bar in bars[:25]]
    result = run(bars)
    assert result["signals"][0]["relativeVolume"] is None
    assert result["signals"][0]["outcome"] == "volume_or_participation_filter"


def test_costs_change_replay_fingerprint_and_cannot_improve_net_pnl():
    costed = run()
    free = run(protocol=parameters(commission_bps=0, spread_bps=0, slippage_bps=0))
    assert free["totalNetPnl"] > costed["totalNetPnl"]
    assert free["parameterFingerprint"] != costed["parameterFingerprint"]
    assert free["inputFingerprint"] == costed["inputFingerprint"]


def test_daily_bar_hitting_stop_and_target_uses_conservative_stop_first():
    bars = synthetic_bars()
    bars[27] = replace(bars[27], low=94, high=105)
    trade = run(bars)["trades"][0]
    assert trade["exitReason"] == "stop_first_ambiguous_daily_bar"
    assert trade["netPnl"] < 0


def test_gap_below_stop_uses_worse_open_not_guaranteed_stop_price():
    bars = synthetic_bars()
    bars[27] = replace(bars[27], high=101, low=98, close=99.5)
    bars.append(replace(bars[-1], session=bars[-1].session + timedelta(days=1),
                        open_at=bars[-1].open_at + timedelta(days=1),
                        observed_at=bars[-1].observed_at + timedelta(days=1),
                        available_at=bars[-1].available_at + timedelta(days=1),
                        open=90, high=92, low=89, close=90))
    trade = run(bars)["trades"][0]
    assert trade["exitReason"] == "gap_below_stop"
    assert trade["exitPrice"] == pytest.approx(90 * .999)


def test_timeout_closes_at_observed_close_and_open_position_is_not_realized():
    bars = synthetic_bars()
    bars[27] = replace(bars[27], high=101, low=98, close=99.5)
    open_result = run(bars)
    assert open_result["trades"] == []
    assert open_result["totalNetPnl"] == 0
    assert open_result["openPosition"]["entryCommissionCost"] > 0
    assert open_result["openPosition"]["unrealizedPnlBeforeExitCosts"] < 0
    closed = run(bars, protocol=parameters(max_holding_sessions=1))
    assert closed["openPosition"] is None
    assert closed["trades"][0]["exitReason"] == "max_holding_sessions"
    assert closed["totalNetPnl"] < 0


@pytest.mark.parametrize("change", [
    {"commission_bps": True}, {"slippage_bps": -1}, {"spread_bps": float("nan")},
    {"min_relative_volume": float("inf")}, {"order_units": 0},
    {"stop_loss_pct": 100}, {"max_volume_participation": 1.01},
    {"max_holding_sessions": True}, {"lookback_sessions": 0},
    {"max_confirmation_sessions": True}, {"min_rebound_pct": -1},
    {"version": "unverified-v2"}, {"slippage_bps": 10000},
])
def test_invalid_or_unversioned_protocol_is_rejected(change):
    with pytest.raises(ValueError):
        run(protocol=parameters(**change))


@pytest.mark.parametrize("kind", ["real", "licensed", "unverified", None])
def test_real_or_unclassified_inputs_are_outside_synthetic_contract(kind):
    with pytest.raises(ValueError, match="synthetic_fixture"):
        run(evidence_kind=kind)


def test_precommit_and_knowledge_cutoff_must_be_time_safe():
    bars = synthetic_bars()
    with pytest.raises(ValueError, match="before the first evaluation"):
        run(bars, precommitted_at=bars[25].open_at + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="available by as_of"):
        run(bars, as_of=bars[-1].available_at - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        run(bars, precommitted_at=bars[0].open_at.replace(tzinfo=None))


def test_missing_duplicate_and_malformed_bars_are_rejected():
    bars = synthetic_bars()
    for candidate in (bars[:25], list(reversed(bars)), bars[:-1] + [bars[-2]],
                      bars[:-1] + [replace(bars[-1], close=True)],
                      bars[:-1] + [replace(bars[-1], low=103)]):
        with pytest.raises(ValueError):
            run(candidate)
    with pytest.raises(ValueError, match="calendar"):
        run(bars[:-1], expected_sessions=[bar.session for bar in bars])


def test_overflow_in_derived_trade_costs_is_not_serialized_as_nan_or_infinity():
    bars = [replace(bar, volume=1e308) for bar in synthetic_bars()]
    with pytest.raises(ValueError):
        run(bars, protocol=parameters(order_units=1e308, max_volume_participation=1,
                                      min_relative_volume=0))


def test_buy_and_hold_uses_fixed_evaluation_window_and_identical_units_and_costs():
    result = run()
    baseline = result["benchmark"]
    assert result["schema"] == "athena.synthetic-rebound-backtest.v1"
    assert result["outputRevision"] == "1.1-buy-and-hold-reporting"
    assert baseline["schema"] == "athena.synthetic-buy-and-hold-benchmark.v1"
    assert baseline["evaluationStartSession"] == "2026-01-26"
    assert baseline["evaluationEndSession"] == "2026-01-28"
    assert baseline["evaluationSessionCount"] == 3
    assert baseline["entryBasePrice"] == 100
    assert baseline["entryPrice"] == pytest.approx(100 * 1.001)
    assert baseline["lastMarkPrice"] == 102
    assert baseline["units"] == result["parameters"]["order_units"] == 10
    assert baseline["costParameters"] == {
        "commission_bps": 5, "spread_bps": 10, "slippage_bps": 5,
    }
    assert baseline["grossMarkToMarketPnl"] == 20
    assert baseline["entryCommissionCost"] == pytest.approx(.5005)
    assert baseline["entrySpreadAndSlippageCost"] == pytest.approx(1)
    assert baseline["netMarkToMarketPnlBeforeExitCosts"] == pytest.approx(18.4995)
    terminal = baseline["hypotheticalLiquidation"]
    assert terminal["exitPrice"] == pytest.approx(101.898)
    assert terminal["totalCommissionCost"] == pytest.approx(1.00999)
    assert terminal["totalSpreadAndSlippageCost"] == pytest.approx(2.02)
    assert terminal["netPnlAfterAllCosts"] == pytest.approx(16.97001)
    assert terminal["isRealized"] is False
    assert baseline["realizedNetPnl"] == 0
    assert baseline["positionClosed"] is False
    assert baseline["performanceValidated"] is False
    assert datetime.fromisoformat(result["precommittedAt"]) <= datetime.fromisoformat(baseline["entryAt"])
    assert datetime.fromisoformat(baseline["lastMarkAvailableAt"]) <= datetime.fromisoformat(result["asOf"])


def test_comparison_never_implies_equal_capital_or_exposure_from_equal_units():
    result = run()
    strategy, baseline = result["strategyAccounting"], result["benchmark"]
    assert strategy["exposedSessionCount"] == 1
    assert strategy["exposureUnitSessions"] == 10
    assert baseline["exposureUnitSessions"] == 30
    assert strategy["realizedNetPnl"] == result["totalNetPnl"]
    assert strategy["openNetMarkToMarketPnlBeforeExitCosts"] == 0
    comparison = result["benchmarkComparison"]
    assert comparison["identicalConfiguredUnits"] is True
    assert comparison["identicalPerSideCostParameters"] is True
    assert comparison["comparableByInitialCapital"] is False
    assert comparison["comparableByExposure"] is False
    assert comparison["outperformanceClaimed"] is False
    assert comparison["hypotheticalLiquidationPnlDifferenceAfterAllCosts"] == pytest.approx(
        result["totalNetPnl"] - baseline["hypotheticalLiquidation"]["netPnlAfterAllCosts"])
    assert comparison["warnings"]


def test_no_strategy_trades_does_not_remove_or_relabel_the_benchmark_position():
    result = run(protocol=parameters(min_relative_volume=3))
    assert result["trades"] == []
    assert result["openPosition"] is None
    assert result["strategyAccounting"]["realizedNetPnl"] == 0
    assert result["strategyAccounting"]["exposureUnitSessions"] == 0
    assert result["benchmark"] == run()["benchmark"]
    assert result["benchmark"]["hypotheticalLiquidation"]["netPnlAfterAllCosts"] != 0


def test_zero_cost_baseline_has_no_hidden_fees_or_price_adjustments():
    free = run(protocol=parameters(commission_bps=0, spread_bps=0, slippage_bps=0))["benchmark"]
    assert free["grossMarkToMarketPnl"] == free["netMarkToMarketPnlBeforeExitCosts"] == 20
    assert free["hypotheticalLiquidation"]["netPnlAfterAllCosts"] == 20
    assert free["hypotheticalLiquidation"]["totalCommissionCost"] == 0
    assert free["hypotheticalLiquidation"]["totalSpreadAndSlippageCost"] == 0
    assert run()["benchmark"]["hypotheticalLiquidation"]["netPnlAfterAllCosts"] < 20


def test_open_strategy_mtm_and_hypothetical_exit_costs_are_not_realized():
    bars = synthetic_bars()
    bars[27] = replace(bars[27], high=101, low=98, close=99.5)
    result = run(bars)
    accounting = result["strategyAccounting"]
    assert result["totalNetPnl"] == accounting["realizedNetPnl"] == 0
    assert accounting["closedTradeCommissionCost"] == 0
    assert accounting["openEntryCommissionCost"] > 0
    assert accounting["openNetMarkToMarketPnlBeforeExitCosts"] == result["openPosition"]["unrealizedPnlBeforeExitCosts"]
    assert accounting["hypotheticalEndLiquidationNetPnlAfterAllCosts"] < accounting["combinedPnlBeforeOpenExitCosts"]
    assert accounting["openHypotheticalLiquidation"]["isRealized"] is False
    assert result["benchmark"]["positionClosed"] is False


def test_benchmark_ignores_warmup_entry_prices_and_does_not_fit_entry_to_last_mark():
    bars = synthetic_bars()
    bars[0] = replace(bars[0], open=200, high=201)
    initial = run(bars)
    assert initial["benchmark"]["entryBasePrice"] == 100
    bars[-1] = replace(bars[-1], close=103.5)
    updated = run(bars)
    assert updated["benchmark"]["entryAt"] == initial["benchmark"]["entryAt"]
    assert updated["benchmark"]["entryPrice"] == initial["benchmark"]["entryPrice"]
    assert updated["trades"] == initial["trades"]
    assert updated["benchmark"]["lastMarkPrice"] != initial["benchmark"]["lastMarkPrice"]
    assert updated["parameterFingerprint"] == initial["parameterFingerprint"]
    assert updated["inputFingerprint"] != initial["inputFingerprint"]


def test_result_fingerprint_covers_additive_benchmark_and_reporting_revision():
    result = run()
    fingerprint = result.pop("resultFingerprint")
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()
    assert digest(result) == fingerprint
    result["benchmark"]["units"] = 11
    assert digest(result) != fingerprint
