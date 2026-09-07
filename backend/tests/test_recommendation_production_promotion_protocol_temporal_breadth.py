from __future__ import annotations

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_promotion_protocol_repository import (
    RecommendationProductionPromotionProtocolRepository,
)


def _draft(*, rows: int = 20, windows: int = 12) -> dict:
    return {
        "artifactVersion": "athena-production-promotion-protocol-v1",
        "protocolId": "temporal-breadth-v1",
        "researchGateFingerprint": "a" * 64,
        "requiredHorizons": [30],
        "criteriaByHorizon": {
            "30": {
                "minimumConfirmationRowCount": rows,
                "minimumNonOverlappingConfirmationWindowCount": windows,
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            }
        },
    }


def test_registered_protocol_persists_precommitted_temporal_breadth(tmp_path) -> None:
    repository = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    record = repository.register(protocol_draft=_draft())
    persisted = repository.get(protocol_id=record["protocol_id"])

    assert persisted is not None
    criterion = persisted["protocol"]["criteriaByHorizon"]["30"]
    assert criterion["minimumConfirmationRowCount"] == 20
    assert criterion["minimumNonOverlappingConfirmationWindowCount"] == 12


def test_temporal_breadth_cannot_exceed_total_confirmation_rows(tmp_path) -> None:
    repository = RecommendationProductionPromotionProtocolRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )

    with pytest.raises(
        ValueError,
        match="minimumNonOverlappingConfirmationWindowCount.*minimumConfirmationRowCount",
    ):
        repository.register(protocol_draft=_draft(rows=20, windows=21))
