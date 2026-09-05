from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_promotion_protocol_repository import (
    RecommendationProductionPromotionProtocolRepository,
)


def _draft(*, protocol_id: str = "prod-promotion-v1") -> dict:
    return {
        "artifactVersion": "athena-production-promotion-protocol-v1",
        "protocolId": protocol_id,
        "researchGateFingerprint": "a" * 64,
        "requiredHorizons": [7, 30, 90, 180, 365],
        "criteriaByHorizon": {
            str(horizon): {
                "minimumSignAccuracy": 0.0,
                "minimumRelativeMseImprovement": 0.0,
                "requireBeatZeroExcessMseBaseline": False,
            }
            for horizon in (7, 30, 90, 180, 365)
        },
    }


def test_registration_timestamp_is_repository_generated_and_persisted(tmp_path):
    repo = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    before = datetime.now(timezone.utc)
    record = repo.register(protocol_draft=_draft())
    after = datetime.now(timezone.utc)

    registered_at = datetime.fromisoformat(record["registered_at"])
    assert before <= registered_at <= after
    assert record["protocol"]["registeredAt"] == record["registered_at"]
    assert record["protocol"]["protocolFingerprint"] == record["protocol_fingerprint"]
    assert repo.get(protocol_id="prod-promotion-v1") == record


def test_callers_cannot_backdate_registration_or_supply_fingerprint(tmp_path):
    repo = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    draft = _draft()
    draft["registeredAt"] = "2000-01-01T00:00:00+00:00"

    with pytest.raises(ValueError, match="los genera el registro"):
        repo.register(protocol_draft=draft)

    draft = _draft()
    draft["protocolFingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="los genera el registro"):
        repo.register(protocol_draft=draft)


def test_protocol_id_cannot_be_reused_to_replace_precommitted_criteria(tmp_path):
    repo = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    repo.register(protocol_draft=_draft())
    changed = _draft()
    changed["criteriaByHorizon"]["365"]["minimumSignAccuracy"] = 1.0

    with pytest.raises(ValueError, match="inmutables"):
        repo.register(protocol_draft=changed)


def test_non_finite_or_incomplete_criteria_are_rejected_before_persistence(tmp_path):
    repo = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    non_finite = _draft(protocol_id="non-finite")
    non_finite["criteriaByHorizon"]["90"]["minimumRelativeMseImprovement"] = float("nan")
    with pytest.raises(ValueError, match="finito"):
        repo.register(protocol_draft=non_finite)

    missing = _draft(protocol_id="missing")
    del missing["criteriaByHorizon"]["180"]
    with pytest.raises(ValueError, match="Faltan criterios"):
        repo.register(protocol_draft=missing)


def test_tampered_persisted_protocol_fails_closed_on_read(tmp_path):
    database = AthenaDatabase(tmp_path / "athena.db")
    repo = RecommendationProductionPromotionProtocolRepository(database)
    record = repo.register(protocol_draft=_draft())
    changed = copy.deepcopy(record["protocol"])
    changed["criteriaByHorizon"]["30"]["minimumSignAccuracy"] = 1.0

    import json

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_production_promotion_protocols
            SET protocol_json = ?
            WHERE protocol_id = ?
            """,
            (
                json.dumps(changed, sort_keys=True, separators=(",", ":")),
                record["protocol_id"],
            ),
        )

    with pytest.raises(ValueError, match="modificado"):
        repo.get(protocol_id=record["protocol_id"])
