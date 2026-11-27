"""Reproducible long-only prior-low rebound hypothesis on explicit synthetic bars.

This is a daily-bar research simulator, not a broker, a recommendation or OOS
acceptance. Stops/targets use a conservative path assumption, not observed fills.
The existing descriptive 20-session pattern service is intentionally unchanged.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from statistics import mean


@dataclass(frozen=True)
class SyntheticReboundBar:
    session: date
    open_at: datetime
    observed_at: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Rebound25Parameters:
    take_profit_pct: float
    stop_loss_pct: float
    max_holding_sessions: int
    commission_bps: float
    spread_bps: float
    slippage_bps: float
    order_units: float
    min_average_volume: float
    max_volume_participation: float
    min_relative_volume: float
    lookback_sessions: int = 25
    min_rebound_pct: float = 1
    max_confirmation_sessions: int = 3
    version: str = "rebound25-synthetic-v1"


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _number(value: object, field: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite JSON number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError(f"{field} must be a finite JSON number") from None
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError(f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def _parameters(parameters: Rebound25Parameters) -> dict:
    if not isinstance(parameters, Rebound25Parameters):
        raise ValueError("parameters must be Rebound25Parameters")
    if parameters.version != "rebound25-synthetic-v1":
        raise ValueError("unsupported hypothesis version")
    result = asdict(parameters)
    for field in ("lookback_sessions", "max_holding_sessions", "max_confirmation_sessions"):
        if type(result[field]) is not int or not 1 <= result[field] <= 252:
            raise ValueError(f"{field} must be an integer between 1 and 252")
    for field in ("take_profit_pct", "stop_loss_pct", "order_units", "min_average_volume",
                  "max_volume_participation"):
        result[field] = _number(result[field], field, positive=True)
    for field in ("commission_bps", "spread_bps", "slippage_bps", "min_relative_volume", "min_rebound_pct"):
        result[field] = _number(result[field], field)
    if result["stop_loss_pct"] >= 100 or result["max_volume_participation"] > 1:
        raise ValueError("stop loss must be below 100%; participation cannot exceed 100%")
    if result["spread_bps"] / 2 + result["slippage_bps"] >= 10000:
        raise ValueError("adverse price cost must be below 100% per side")
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def run_rebound25_synthetic_backtest(
    bars: list[SyntheticReboundBar], *, parameters: Rebound25Parameters,
    expected_sessions: list[date], as_of: datetime, precommitted_at: datetime,
    instrument_id: str, currency: str, evidence_kind: str,
) -> dict:
    """Evaluate a prior-low hypothesis with next-open entry and explicit costs.

    The default lookback is exactly 25 prior LOWs, excluding the breach bar.
    A breach is only a pending hypothesis. A later session must CLOSE strictly
    above the breach close plus min_rebound_pct within max_confirmation_sessions.
    Entry is at the opening after that confirmation became available. The breach
    baseline never changes to include the confirmation. Other configured windows
    are separate fingerprints. Breach RVOL uses the same prior window; entry
    participation uses known confirmation volume, never future entry-day volume.
    """
    if evidence_kind != "synthetic_fixture":
        raise ValueError("this backtest accepts explicitly synthetic_fixture evidence only")
    if (not isinstance(instrument_id, str) or not instrument_id.strip()
            or instrument_id != instrument_id.strip()):
        raise ValueError("instrument_id is required")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isupper() or not currency.isalpha():
        raise ValueError("currency must be an ASCII ISO-style currency code")
    protocol = _parameters(parameters)
    cutoff = _utc(as_of, "as_of")
    precommit = _utc(precommitted_at, "precommitted_at")
    lookback = protocol["lookback_sessions"]
    if (not isinstance(bars, list) or not lookback < len(bars) <= 5000
            or not isinstance(expected_sessions, list) or len(expected_sessions) != len(bars)
            or any(type(day) is not date for day in expected_sessions)
            or expected_sessions != sorted(set(expected_sessions))):
        raise ValueError("provide an ordered, complete caller-supplied session calendar and enough bars")
    canonical = []
    previous_close = None
    for index, bar in enumerate(bars):
        if not isinstance(bar, SyntheticReboundBar) or bar.session != expected_sessions[index]:
            raise ValueError("bars must exactly match expected_sessions without duplicates or gaps")
        opened = _utc(bar.open_at, "open_at")
        observed = _utc(bar.observed_at, "observed_at")
        available = _utc(bar.available_at, "available_at")
        if (not opened < observed <= available <= cutoff
                or (previous_close is not None and opened <= previous_close)):
            raise ValueError("bars must be final, nonoverlapping and available by as_of")
        previous_close = observed
        values = {field: _number(getattr(bar, field), field, positive=field != "volume")
                  for field in ("open", "high", "low", "close", "volume")}
        if (values["low"] > min(values["open"], values["close"])
                or values["high"] < max(values["open"], values["close"])):
            raise ValueError("inconsistent OHLC range")
        canonical.append({"session": bar.session.isoformat(), "openAt": opened.isoformat(),
                          "observedAt": observed.isoformat(), "availableAt": available.isoformat(),
                          **values})
    if precommit > datetime.fromisoformat(canonical[lookback]["openAt"]):
        raise ValueError("parameters must be declared before the first evaluation session opens")
    price_cost = (protocol["spread_bps"] / 2 + protocol["slippage_bps"]) / 10000
    fee_rate = protocol["commission_bps"] / 10000
    signals, trades, abstentions = [], [], []
    position = None
    pending = None
    for index in range(lookback, len(bars)):
        bar = canonical[index]
        if position is not None:
            held = index - position["entryIndex"] + 1
            base_exit = reason = None
            if bar["open"] <= position["stop"]:
                base_exit, reason = bar["open"], "gap_below_stop"
            elif bar["open"] >= position["target"]:
                base_exit, reason = bar["open"], "gap_above_target"
            elif bar["low"] <= position["stop"]:
                base_exit = position["stop"]
                reason = ("stop_first_ambiguous_daily_bar" if bar["high"] >= position["target"]
                          else "stop_loss")
            elif bar["high"] >= position["target"]:
                base_exit, reason = position["target"], "rebound_target"
            elif held >= protocol["max_holding_sessions"]:
                base_exit, reason = bar["close"], "max_holding_sessions"
            if base_exit is not None:
                exit_price = base_exit * (1 - price_cost)
                units = protocol["order_units"]
                commission = (position["entryPrice"] + exit_price) * units * fee_rate
                gross_pnl = (base_exit - position["entryBase"]) * units
                execution_pnl = (exit_price - position["entryPrice"]) * units
                net_pnl = execution_pnl - commission
                trades.append({
                    "signalSession": position["signalSession"],
                    "entrySession": canonical[position["entryIndex"]]["session"],
                    "exitSession": bar["session"], "holdingSessions": held,
                    "decisionAt": position["decisionAt"],
                    "breachDecisionAt": position["breachDecisionAt"],
                    "confirmationSession": position["confirmationSession"],
                    "confirmationDecisionAt": position["decisionAt"],
                    "entryAt": canonical[position["entryIndex"]]["openAt"],
                    "exitEvidenceAvailableAt": bar["availableAt"],
                    "entryPrice": position["entryPrice"], "exitPrice": exit_price,
                    "units": units, "grossPnl": gross_pnl,
                    "spreadAndSlippageCost": gross_pnl - execution_pnl,
                    "commissionCost": commission, "netPnl": net_pnl,
                    "netReturnPct": net_pnl / (position["entryPrice"] * units * (1 + fee_rate)) * 100,
                    "exitReason": reason,
                })
                position = None
            # No signal/re-entry on a session already used by an open position.
            continue
        if pending is not None:
            signal = signals[pending["signalIndex"]]
            waited = index - pending["breachIndex"]
            if bar["close"] > pending["confirmationThreshold"]:
                confirmation_at = datetime.fromisoformat(bar["availableAt"])
                reason = "next_open_simulated_entry"
                if confirmation_at <= datetime.fromisoformat(signal["decisionAt"]):
                    reason = "confirmation_not_available_after_breach"
                elif protocol["order_units"] > bar["volume"] * protocol["max_volume_participation"]:
                    reason = "confirmation_volume_or_participation_filter"
                elif index + 1 >= len(canonical):
                    reason = "next_session_unavailable"
                elif datetime.fromisoformat(canonical[index + 1]["openAt"]) <= confirmation_at:
                    reason = "confirmation_not_available_before_next_open"
                signal.update({"confirmationSession": bar["session"],
                               "confirmationDecisionAt": confirmation_at.isoformat(),
                               "confirmationClose": bar["close"], "outcome": reason})
                if reason == "next_open_simulated_entry":
                    entry_base = canonical[index + 1]["open"]
                    position = {"entryIndex": index + 1, "entryBase": entry_base,
                                "entryPrice": entry_base * (1 + price_cost),
                                "stop": entry_base * (1 - protocol["stop_loss_pct"] / 100),
                                "target": entry_base * (1 + protocol["take_profit_pct"] / 100),
                                "signalSession": signal["session"],
                                "breachDecisionAt": signal["decisionAt"],
                                "confirmationSession": bar["session"],
                                "decisionAt": confirmation_at.isoformat()}
                else:
                    abstentions.append({"session": bar["session"], "reason": reason})
                pending = None
            elif waited >= protocol["max_confirmation_sessions"]:
                signal["outcome"] = "rebound_confirmation_expired"
                abstentions.append({"session": bar["session"], "reason": "rebound_confirmation_expired"})
                pending = None
            continue
        reference = canonical[index - lookback:index]
        decision = datetime.fromisoformat(bar["availableAt"])
        if any(datetime.fromisoformat(item["availableAt"]) > decision for item in reference):
            abstentions.append({"session": bar["session"],
                                "reason": "prior_evidence_not_yet_available"})
            continue
        prior_low = min(item["low"] for item in reference)
        if bar["close"] >= prior_low:
            continue
        average_volume = mean(item["volume"] for item in reference)
        rvol = bar["volume"] / average_volume if average_volume > 0 else None
        reason = "awaiting_rebound_confirmation"
        if (average_volume < protocol["min_average_volume"] or rvol is None
                or rvol < protocol["min_relative_volume"]
                or protocol["order_units"] > bar["volume"] * protocol["max_volume_participation"]):
            reason = "volume_or_participation_filter"
        signals.append({"session": bar["session"], "decisionAt": decision.isoformat(),
                        "priorLow": prior_low, "referenceSessionCount": lookback,
                        "breachClose": bar["close"],
                        "confirmationThreshold": bar["close"] * (1 + protocol["min_rebound_pct"] / 100),
                        "relativeVolume": rvol, "outcome": reason})
        if reason == "awaiting_rebound_confirmation":
            pending = {"breachIndex": index, "signalIndex": len(signals) - 1,
                       "confirmationThreshold": signals[-1]["confirmationThreshold"]}
    pending_hypothesis = None
    if pending is not None:
        signal = signals[pending["signalIndex"]]
        signal["outcome"] = "rebound_confirmation_unavailable_at_end"
        pending_hypothesis = {"breachSession": signal["session"],
                              "confirmationThreshold": pending["confirmationThreshold"],
                              "reason": signal["outcome"]}
    open_position = None
    if position is not None:
        units = protocol["order_units"]
        open_position = {"signalSession": position["signalSession"],
                         "entrySession": canonical[position["entryIndex"]]["session"],
                         "entryPrice": position["entryPrice"], "units": units,
                         "entryCommissionCost": position["entryPrice"] * units * fee_rate,
                         "lastClose": canonical[-1]["close"],
                         "unrealizedPnlBeforeExitCosts": (
                             (canonical[-1]["close"] - position["entryPrice"]) * units
                             - position["entryPrice"] * units * fee_rate)}
    result = {
        "schema": "athena.synthetic-rebound-backtest.v1", "parameters": protocol,
        "parameterFingerprint": _hash(protocol), "inputFingerprint": _hash(canonical),
        "instrumentId": instrument_id, "currency": currency,
        "asOf": cutoff.isoformat(), "precommittedAt": precommit.isoformat(),
        "precommitBasis": "caller_declared_not_immutable_attestation",
        "calendarBasis": "caller_supplied_sessions_not_exchange_attested",
        "evidenceKind": "synthetic_fixture", "signals": signals, "trades": trades,
        "abstentions": abstentions,
        "openPosition": open_position, "pendingHypothesis": pending_hypothesis,
        "totalNetPnl": sum(trade["netPnl"] for trade in trades),
        "closedTradeCount": len(trades), "positionModel": "one_long_position_fixed_units_no_leverage",
        "fillModel": "confirmed_rebound_then_next_open_daily_ohlc_exit_stop_first_if_ambiguous",
        "thresholdBasis": "unadjusted_next_open_before_costs",
        "commissionTreatment": "per_side_executed_notional",
        "spreadTreatment": "half_configured_full_spread_per_side",
        "volumeBasis": "breach_rvol_and_confirmation_volume_known_before_entry_not_entry_session_volume",
        "productionEligible": False, "historicalPointInTimeEligible": False,
        "outOfSampleValidated": False, "automaticTrading": False, "ordersEnabled": False,
        "advisoryStatus": "no_advice",
        "warnings": ["Synthetic hypothesis only; no investment-performance claim.",
                     "Daily OHLC does not establish intraday path, actual fills or exit liquidity.",
                     "No survivorship-safe universe, independent calendar or OOS acceptance is established.",
                     "Open positions are not silently closed or counted as realized profits."],
    }
    # Finite inputs can still overflow derived arithmetic. Fail the whole
    # simulation rather than returning NaN/Infinity or a non-replayable artifact.
    result["resultFingerprint"] = _hash(result)
    return result
