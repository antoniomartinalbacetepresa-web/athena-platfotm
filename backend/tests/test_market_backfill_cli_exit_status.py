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
