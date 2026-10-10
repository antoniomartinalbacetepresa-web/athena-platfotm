from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_shadow_action_threshold_freeze_service import (
    RecommendationShadowActionThresholdFreezeService,
)


PANEL_FINGERPRINT = "b" * 64


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


def _selection(*, eligible=True, panel_fingerprint=PANEL_FINGERPRINT):
    return {
        "sourceUtilityPanelFingerprint": panel_fingerprint,
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


def _panel(evaluated_at=None, *, panel_fingerprint=PANEL_FINGERPRINT):
    result = {"utilityPanelFingerprint": panel_fingerprint}
    if evaluated_at is not None:
        result["validationUtilityRows"] = [
            {"outcomeEvaluatedAt": evaluated_at.isoformat()}
        ]
    return result


def _service(selection, repository=None, *, now=None):
    clock_value = now or datetime(2026, 2, 1, tzinfo=timezone.utc)
    return RecommendationShadowActionThresholdFreezeService(
        selection_service=_SelectionService(selection),
        selection_repository=repository or _Repository(),
        clock=lambda: clock_value,
    )


def test_freezes_complete_selection_before_future_confirmation():
    selected_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    observed_at = selected_at - timedelta(days=1)
    result = _service(_selection(), now=selected_at).freeze(
        utility_panel=_panel(observed_at),
    )

    assert result["status"] == "shadow_action_thresholds_frozen_before_future_confirmation"
    assert result["artifactVersion"] == "shadow-action-threshold-freeze-v3"
    assert result["sourceUtilityPanelFingerprint"] == PANEL_FINGERPRINT
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
    assert result["policy"]["selectionBoundToUtilityPanelFingerprint"] is True
    assert result["policy"]["callerSuppliedSelectionTimestampAccepted"] is False
    assert result["policy"]["futureEvidenceBeforeSelectedAtMayBeUsed"] is False
    assert result["policy"]["futureReserveMayRefitThresholds"] is False
    assert result["policy"]["futureReserveMayReselectPolicies"] is False
    assert result["policy"]["automaticTrading"] is False


def test_repeated_freeze_cannot_move_first_selection_boundary():
    repo = _Repository()
    first_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    later_at = first_at + timedelta(days=30)
    panel = _panel(first_at - timedelta(days=1))

    first = _service(_selection(), repository=repo, now=first_at).freeze(
        utility_panel=panel
    )
    second = _service(_selection(), repository=repo, now=later_at).freeze(
        utility_panel=panel
    )

    assert first["selectedAt"] == first_at.isoformat()
    assert second["selectedAt"] == first_at.isoformat()
    assert first["freezeFingerprint"] == second["freezeFingerprint"]


def test_insufficient_selection_is_not_registered_or_clock_gated():
    repo = _Repository()
    result = _service(_selection(eligible=False), repository=repo).freeze(
        utility_panel=_panel(),
    )

    assert result["status"] == "shadow_action_threshold_freeze_insufficient"
    assert result["sourceUtilityPanelFingerprint"] == PANEL_FINGERPRINT
    assert result["registered"] is False
    assert result["futureReserveConfirmationEligible"] is False
    assert result["actionThresholdCalibrationResearchEligible"] is False
    assert result["actionThresholds"] is None
    assert repo.record is None


def test_rejects_selection_from_different_utility_panel():
    selection = _selection(panel_fingerprint="c" * 64)

    with pytest.raises(ValueError, match="no pertenece al panel"):
        _service(selection).freeze(
            utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc)),
        )


def test_rejects_missing_utility_panel_fingerprint_before_selection_freeze():
    with pytest.raises(ValueError, match="utilityPanelFingerprint"):
        _service(_selection()).freeze(
            utility_panel={
                "validationUtilityRows": [
                    {
                        "outcomeEvaluatedAt": datetime(
                            2026, 1, 31, tzinfo=timezone.utc
                        ).isoformat()
                    }
                ]
            },
        )


def test_rejects_backdated_service_clock_against_observed_validation():
    freeze_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    observed_at = freeze_at + timedelta(seconds=1)

    with pytest.raises(ValueError, match="anterior a evidencia"):
        _service(_selection(), now=freeze_at).freeze(
            utility_panel=_panel(observed_at),
        )


def test_rejects_eligible_freeze_without_temporal_validation_evidence():
    with pytest.raises(ValueError, match="validationUtilityRows"):
        _service(_selection()).freeze(utility_panel=_panel())


def test_rejects_naive_service_clock():
    service = RecommendationShadowActionThresholdFreezeService(
        selection_service=_SelectionService(_selection()),
        selection_repository=_Repository(),
        clock=lambda: datetime(2026, 2, 1),
    )

    with pytest.raises(ValueError, match="zona horaria"):
        service.freeze(
            utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc))
        )


def test_rejects_selection_that_consumed_future_reserve():
    selection = _selection()
    selection["policy"]["futureReserveConsumed"] = True

    with pytest.raises(ValueError, match="reserva futura"):
        _service(selection).freeze(
            utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc)),
        )


def test_rejects_selection_that_allows_future_refit():
    selection = _selection()
    selection["policy"]["selectedResearchThresholdsMayBeRefitOnFutureReserve"] = True

    with pytest.raises(ValueError, match="refit"):
        _service(selection).freeze(
            utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc)),
        )


def test_rejects_production_escape_before_persistence():
    for field, value in (
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("actionThresholds", {"buy": 0.1}),
        ("action", "buy"),
        ("score", 0.7),
        ("conviction", 0.7),
    ):
        selection = _selection()
        selection[field] = value
        with pytest.raises(ValueError):
            _service(selection).freeze(
                utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc)),
            )


def test_rejects_repository_that_substitutes_record():
    with pytest.raises(ValueError, match="sustituyó"):
        _service(_selection(), repository=_ReplacingRepository()).freeze(
            utility_panel=_panel(datetime(2026, 1, 31, tzinfo=timezone.utc)),
        )
