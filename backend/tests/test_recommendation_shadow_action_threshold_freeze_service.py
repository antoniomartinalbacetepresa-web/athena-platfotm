from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_action_threshold_freeze_service import (
    RecommendationShadowActionThresholdFreezeService,
)


class _SelectionService:
    def __init__(self, selection):
        self.selection = selection

    def select(self, utility_panel):
        return self.selection


class _Repository:
    def __init__(self):
        self.record = None

    def register(self, *, selection, selected_at):
        if self.record is None:
            self.record = {
                "selection_fingerprint": selection["selectionFingerprint"],
                "selected_at": selected_at.isoformat(),
                "selection": copy.deepcopy(selection),
                "registration_fingerprint": "d" * 64,
            }
        return self.record

    def get(self, *, selection_fingerprint):
        if self.record is None:
            return None
        if self.record["selection_fingerprint"] != selection_fingerprint:
            return None
        return self.record

    def validate_record(self, record):
        return record


class _ReplacingRepository(_Repository):
    def validate_record(self, record):
        return copy.deepcopy(record)


def _policy():
    return {
        "candidateGenerationPartition": "train_signal_only",
        "candidateSelectionPartition": "validation_only",
        "trainRealizedOutcomesUsedForSelection": False,
        "futureReserveConsumed": False,
        "selectedResearchThresholdsMayBeRefitOnFutureReserve": False,
        "automaticProductionPromotion": False,
        "automaticTrading": False,
    }


def _selection(*, eligible=True):
    return {
        "selectionFingerprint": "a" * 64,
        "futureReserveConfirmationEligible": eligible,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "actionThresholds": None,
        "action": None,
        "score": None,
        "conviction": None,
        "policy": _policy(),
    }


def _service(selection, repository=None):
    return RecommendationShadowActionThresholdFreezeService(
        selection_service=_SelectionService(selection),
        selection_repository=repository or _Repository(),
    )


def test_freezes_complete_selection_before_future_confirmation():
    selected_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = _service(_selection()).freeze(
        utility_panel={"synthetic": True},
        selected_at=selected_at,
    )

    assert result["status"] == "shadow_action_thresholds_frozen_before_future_confirmation"
    assert result["registered"] is True
    assert result["selectedAt"] == selected_at.isoformat()
    assert result["futureReserveConfirmationEligible"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["policy"]["futureEvidenceBeforeSelectedAtMayBeUsed"] is False
    assert result["policy"]["futureReserveMayRefitThresholds"] is False
    assert result["policy"]["futureReserveMayReselectPolicies"] is False
    assert result["policy"]["automaticTrading"] is False


def test_repeated_freeze_cannot_move_first_selection_boundary():
    repo = _Repository()
    service = _service(_selection(), repository=repo)
    first_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later_at = first_at + timedelta(days=30)

    first = service.freeze(utility_panel={}, selected_at=first_at)
    second = service.freeze(utility_panel={}, selected_at=later_at)

    assert first["selectedAt"] == first_at.isoformat()
    assert second["selectedAt"] == first_at.isoformat()
    assert first["freezeFingerprint"] == second["freezeFingerprint"]


def test_insufficient_selection_is_not_registered():
    repo = _Repository()
    result = _service(_selection(eligible=False), repository=repo).freeze(
        utility_panel={},
        selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "shadow_action_threshold_freeze_insufficient"
    assert result["registered"] is False
    assert result["futureReserveConfirmationEligible"] is False
    assert repo.record is None


def test_rejects_selection_that_consumed_future_reserve():
    selection = _selection()
    selection["policy"]["futureReserveConsumed"] = True

    with pytest.raises(ValueError, match="reserva futura"):
        _service(selection).freeze(
            utility_panel={},
            selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_rejects_selection_that_allows_future_refit():
    selection = _selection()
    selection["policy"]["selectedResearchThresholdsMayBeRefitOnFutureReserve"] = True

    with pytest.raises(ValueError, match="refit"):
        _service(selection).freeze(
            utility_panel={},
            selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_rejects_production_escape_before_persistence():
    for field, value in (
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("action", "buy"),
        ("score", 0.7),
        ("conviction", 0.7),
    ):
        selection = _selection()
        selection[field] = value
        with pytest.raises(ValueError):
            _service(selection).freeze(
                utility_panel={},
                selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )


def test_rejects_repository_that_substitutes_record():
    with pytest.raises(ValueError, match="sustituyó"):
        _service(_selection(), repository=_ReplacingRepository()).freeze(
            utility_panel={},
            selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
