"""Operational backfill CLI exit status must not certify incomplete work."""

from __future__ import annotations

import json
import sys

import pytest

from scripts import backfill_deep_market_history as deep
from scripts import backfill_market_observations as generic


@pytest.mark.parametrize(("ready", "expected"), [
    (True, 0), (False, 3), ("true", 3), (None, 3),
])
def test_deep_single_batch_requires_complete_365_day_criterion(
    monkeypatch, capsys, ready, expected,
):
    payload = {"verification": {"deepHistoryCriterionSatisfied": ready}}
    monkeypatch.setattr(deep, "run", lambda **kwargs: payload)
    monkeypatch.setattr(sys, "argv", ["backfill_deep_market_history"])
    assert deep.main() == expected
    assert json.loads(capsys.readouterr().out) == payload


@pytest.mark.parametrize(("ready", "expected"), [
    (True, 0), (False, 3), ("true", 3), (None, 3),
])
def test_deep_sweep_requires_complete_365_day_criterion(
    monkeypatch, capsys, ready, expected,
):
    payload = {"historyReady": ready}
    monkeypatch.setattr(deep, "run_sweep", lambda **kwargs: payload)
    monkeypatch.setattr(sys, "argv", ["backfill_deep_market_history", "--sweep"])
    assert deep.main() == expected
    assert json.loads(capsys.readouterr().out) == payload


@pytest.mark.parametrize(("failed", "missing", "expected"), [
    (0, 0, 0), (1, 0, 3), (0, 1, 3), (1, 1, 3),
    (None, 0, 3), (0, None, 3), (False, 0, 3),
])
def test_generic_backfill_rejects_partial_provider_results(
    monkeypatch, capsys, failed, missing, expected,
):
    payload = {"failedCount": failed, "noHistoryCount": missing}
    monkeypatch.setattr(generic, "run", lambda **kwargs: payload)
    monkeypatch.setattr(sys, "argv", ["backfill_market_observations"])
    assert generic.main() == expected
    assert json.loads(capsys.readouterr().out) == payload



@pytest.mark.parametrize(("failed", "expected"), [(0, 0), (2, 3), (None, 3), (False, 3)])
def test_plain_secondary_backfill_cli_does_not_hide_provider_failures(
    monkeypatch, capsys, failed, expected,
):
    from scripts import backfill_secondary_corporate_actions as secondary
    payload = {"failedCount": failed, "provider": "alpha_vantage"}
    monkeypatch.setattr(secondary, "run", lambda **kwargs: payload)
    monkeypatch.setattr(sys, "argv", ["backfill_secondary_corporate_actions"])
    assert secondary.main() == expected
    assert json.loads(capsys.readouterr().out) == payload


@pytest.mark.parametrize(("payload", "expected"), [
    ({"failedCount": 0, "selectedEventsStillIncomplete": 0, "selectedEventsConflicting": 0}, 0),
    ({"failedCount": 1, "selectedEventsStillIncomplete": 0, "selectedEventsConflicting": 0}, 3),
    ({"failedCount": 0, "selectedEventsStillIncomplete": 1, "selectedEventsConflicting": 0}, 3),
    ({"failedCount": 0, "selectedEventsStillIncomplete": 0, "selectedEventsConflicting": 1}, 3),
    ({"failedCount": 0, "selectedEventsStillIncomplete": None, "selectedEventsConflicting": 0}, 3),
])
def test_verified_secondary_single_batch_cli_requires_selected_events_resolved(
    monkeypatch, capsys, payload, expected,
):
    from scripts import backfill_verified_secondary_corporate_actions as secondary
    monkeypatch.setattr(secondary, "run", lambda **kwargs: payload)
    monkeypatch.setattr(sys, "argv", ["backfill_verified_secondary_corporate_actions"])
    assert secondary.main() == expected
    assert json.loads(capsys.readouterr().out) == payload
