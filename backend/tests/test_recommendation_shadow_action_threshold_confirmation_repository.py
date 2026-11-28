from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_shadow_action_threshold_confirmation_repository import (
    RecommendationShadowActionThresholdConfirmationRepository,
)


def _confirmation(value=0.01):
    return {
        "status": "shadow_action_threshold_future_confirmation_sealed",
        "selectionFingerprint": "a" * 64,
        "metric": value,
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def test_first_confirmation_is_immutable(tmp_path):
    repo = RecommendationShadowActionThresholdConfirmationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    first_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    first = repo.seal(
        selection_fingerprint="a" * 64,
        confirmation=_confirmation(0.01),
        sealed_at=first_at,
    )
    second = repo.seal(
        selection_fingerprint="a" * 64,
        confirmation=_confirmation(999.0),
        sealed_at=first_at + timedelta(days=30),
    )

    assert first["confirmation"] == _confirmation(0.01)
    assert second["confirmation"] == _confirmation(0.01)
    assert second["sealed_at"] == first_at.isoformat()
    assert second["confirmation_fingerprint"] == first["confirmation_fingerprint"]


def test_confirmation_must_match_selection_fingerprint(tmp_path):
    repo = RecommendationShadowActionThresholdConfirmationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    confirmation = _confirmation()
    confirmation["selectionFingerprint"] = "b" * 64

    with pytest.raises(ValueError, match="no pertenece"):
        repo.seal(
            selection_fingerprint="a" * 64,
            confirmation=confirmation,
            sealed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )


def test_sealed_at_requires_timezone(tmp_path):
    repo = RecommendationShadowActionThresholdConfirmationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(ValueError, match="zona horaria"):
        repo.seal(
            selection_fingerprint="a" * 64,
            confirmation=_confirmation(),
            sealed_at=datetime(2026, 6, 1),
        )


def test_tampered_confirmation_record_is_rejected(tmp_path):
    repo = RecommendationShadowActionThresholdConfirmationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    record = repo.seal(
        selection_fingerprint="a" * 64,
        confirmation=_confirmation(),
        sealed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    changed = copy.deepcopy(record)
    changed["confirmation"]["metric"] = 999.0

    with pytest.raises(ValueError, match="modificada"):
        repo.validate_record(changed)


def test_get_revalidates_persisted_payload(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationShadowActionThresholdConfirmationRepository(database)
    repo.seal(
        selection_fingerprint="a" * 64,
        confirmation=_confirmation(),
        sealed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_shadow_action_threshold_confirmations
            SET confirmation_json = ?
            WHERE selection_fingerprint = ?
            """,
            ('{"selectionFingerprint":"' + "a" * 64 + '","metric":999}', "a" * 64),
        )

    with pytest.raises(ValueError, match="modificada"):
        repo.get(selection_fingerprint="a" * 64)
