from __future__ import annotations

import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_athena_synthesis_repository import (
    RecommendationAthenaSynthesisRepository,
)
from app.repositories.recommendation_latest_athena_synthesis_repository import (
    RecommendationLatestAthenaSynthesisRepository,
)


A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64


def _payload(*, cycle_hash: str, input_fingerprint: str, output_fingerprint: str) -> dict:
    return {
        "status": "validated_external_athena_synthesis",
        "mode": "research_explanation_only",
        "cycleHash": cycle_hash,
        "radarHash": B,
        "modelExecutionVerified": False,
        "productionEligible": False,
        "isWeightingReady": False,
        "recommendationInfluence": False,
        "automaticScoring": False,
        "automaticTrading": False,
        "automaticProductionPromotion": False,
        "advisoryStatus": "no_advice",
        "inputFingerprint": input_fingerprint,
        "outputFingerprint": output_fingerprint,
        "uncertainties": ["Longitudinal evidence remains incomplete."],
        "evidenceIds": ["investors:1"],
        "coveredCategories": ["investors"],
    }


def test_latest_selection_returns_newest_canonical_record(tmp_path) -> None:
    database = AthenaDatabase(path=tmp_path / "athena.db")
    canonical = RecommendationAthenaSynthesisRepository(database)
    first = canonical.append(
        cycle_hash=A,
        radar_hash=B,
        news_synthesis_hash=None,
        synthesis_payload=_payload(cycle_hash=A, input_fingerprint=C, output_fingerprint=D),
    )
    second = canonical.append(
        cycle_hash=E,
        radar_hash=B,
        news_synthesis_hash=None,
        synthesis_payload=_payload(cycle_hash=E, input_fingerprint=C, output_fingerprint=F),
    )

    latest = RecommendationLatestAthenaSynthesisRepository(database).get_latest()

    assert latest["cycle_hash"] == E
    assert latest["synthesis_hash"] == second["synthesis_hash"]
    assert latest["synthesis_hash"] != first["synthesis_hash"]
    assert latest["package"]["synthesis"]["recommendationInfluence"] is False
    assert latest["package"]["synthesis"]["automaticTrading"] is False


def test_latest_selection_fails_closed_when_empty(tmp_path) -> None:
    database = AthenaDatabase(path=tmp_path / "athena.db")

    with pytest.raises(ValueError, match="No existe ninguna ATHENA synthesis persistida"):
        RecommendationLatestAthenaSynthesisRepository(database).get_latest()


def test_latest_selection_revalidates_package_integrity(tmp_path) -> None:
    database = AthenaDatabase(path=tmp_path / "athena.db")
    canonical = RecommendationAthenaSynthesisRepository(database)
    canonical.append(
        cycle_hash=A,
        radar_hash=B,
        news_synthesis_hash=None,
        synthesis_payload=_payload(cycle_hash=A, input_fingerprint=C, output_fingerprint=D),
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT package_json FROM athena_research_syntheses WHERE cycle_hash = ?",
            (A,),
        ).fetchone()
        package = json.loads(str(row["package_json"]))
        package["synthesis"]["automaticTrading"] = True
        connection.execute(
            "UPDATE athena_research_syntheses SET package_json = ? WHERE cycle_hash = ?",
            (json.dumps(package), A),
        )

    with pytest.raises(ValueError, match="automaticTrading=false"):
        RecommendationLatestAthenaSynthesisRepository(database).get_latest()
