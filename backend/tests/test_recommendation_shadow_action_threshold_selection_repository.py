from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_action_threshold_selection_repository import (
    RecommendationShadowActionThresholdSelectionRepository,
)
from app.services.recommendation_shadow_action_threshold_selection_service import (
    RecommendationShadowActionThresholdSelectionService,
)


class _IdentityPanelValidator:
    def validate_artifact(self, artifact):
        return artifact


def _row(*, candidate_id: int, signal: float, state: str, partition: str):
    realized = 0.1 if signal > 0 else -0.1
    allowed = {
        "flat": {
            "hold": {"netRealizedExcessUtility": 0.0},
            "buy": {"netRealizedExcessUtility": realized - 0.001},
        },
        "reduced_long": {
            "hold": {"netRealizedExcessUtility": 0.5 * realized},
            "buy": {"netRealizedExcessUtility": realized - 0.001},
            "sell": {"netRealizedExcessUtility": -0.001},
        },
        "full_long": {
            "hold": {"netRealizedExcessUtility": realized},
            "reduce": {"netRealizedExcessUtility": 0.5 * realized - 0.001},
            "sell": {"netRealizedExcessUtility": -0.001},
        },
    }[state]
    return {
        "partition": partition,
        "candidateId": candidate_id,
        "horizonDays": 30,
        "currentState": state,
        "expectedExcessReturn": signal,
        "realizedExcessReturn": realized,
        "allowedActionUtilities": allowed,
    }


def _selection():
    states = ("flat", "reduced_long", "full_long")
    train = []
    for candidate_id, signal in enumerate((-0.1, -0.03, 0.02, 0.09), start=1):
        for state in states:
            train.append(
                _row(
                    candidate_id=candidate_id,
                    signal=signal,
                    state=state,
                    partition="train",
                )
            )
    validation = []
    for offset in range(12):
        signal = -0.06 if offset % 2 == 0 else 0.06
        for state in states:
            validation.append(
                _row(
                    candidate_id=100 + offset,
                    signal=signal,
                    state=state,
                    partition="validation",
                )
            )
    panel = {
        "utilityPanelFingerprint": "a" * 64,
        "economicContractFingerprint": "b" * 64,
        "positionStates": list(states),
        "requestedHorizons": [30],
        "trainUtilityRows": train,
        "validationUtilityRows": validation,
    }
    return RecommendationShadowActionThresholdSelectionService(
        panel_validator=_IdentityPanelValidator()
    ).select(panel)


def test_first_threshold_selection_boundary_is_immutable(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    selection = _selection()
    first_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later_at = first_at + timedelta(days=30)

    first = repo.register(selection=selection, selected_at=first_at)
    second = repo.register(selection=selection, selected_at=later_at)

    assert first["registration_fingerprint"] == second["registration_fingerprint"]
    assert first["selected_at"] == first_at.isoformat()
    assert second["selected_at"] == first_at.isoformat()
    assert second["selection_fingerprint"] == selection["selectionFingerprint"]


def test_selection_timestamp_requires_timezone(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="zona horaria"):
        repo.register(
            selection=_selection(),
            selected_at=datetime(2026, 1, 1),
        )


def test_incomplete_selection_cannot_be_registered(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    selection = _selection()
    selection["status"] = "shadow_action_threshold_selection_insufficient"

    with pytest.raises(ValueError, match="completa"):
        repo.register(
            selection=selection,
            selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_tampered_selection_fingerprint_is_rejected(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    selection = _selection()
    selection["selections"]["30"]["states"]["flat"]["selectedPolicy"][
        "meanNetRealizedExcessUtility"
    ] = 999.0

    with pytest.raises(ValueError, match="modificada"):
        repo.register(
            selection=selection,
            selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_tampered_persisted_registration_is_rejected(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    record = repo.register(
        selection=_selection(),
        selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    changed = copy.deepcopy(record)
    changed["selected_at"] = datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat()

    with pytest.raises(ValueError, match="modificado"):
        repo.validate_record(changed)


def test_registration_rejects_production_or_advisory_escape(tmp_path):
    repo = RecommendationShadowActionThresholdSelectionRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    for field, value in (
        ("productionEligible", True),
        ("recommendationCandidateReady", True),
        ("actionThresholdCalibrationResearchEligible", True),
        ("action", "buy"),
        ("score", 0.9),
        ("conviction", 0.9),
    ):
        selection = _selection()
        selection[field] = value
        with pytest.raises(ValueError):
            repo.register(
                selection=selection,
                selected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
