from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_athena_synthesis_repository import (
    RecommendationAthenaSynthesisRepository,
)
from app.services.recommendation_athena_synthesis_service import (
    AthenaSynthesisModelInput,
    RecommendationAthenaSynthesisService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
CYCLE_HASH = "1" * 64
RADAR_HASH = "2" * 64
NEWS_HASH = "3" * 64


def _cycle_record() -> dict[str, object]:
    return {
        "cycle_hash": CYCLE_HASH,
        "radar_hash": RADAR_HASH,
        "package": {
            "cycle": {
                "asOf": AS_OF.isoformat(),
                "integrity": {"cycleHash": CYCLE_HASH, "radarHash": RADAR_HASH},
            },
            "radar": {
                "asOf": AS_OF.isoformat(),
                "candidates": [
                    {
                        "instrumentId": "instrument-aapl",
                        "symbol": "AAPL",
                        "evidence": [
                            {"evidenceId": "news-1", "category": "news"},
                            {"evidenceId": "risk-1", "category": "factor_risk"},
                        ],
                    }
                ],
            },
        },
    }


def _news_record() -> dict[str, object]:
    return {
        "cycle_hash": CYCLE_HASH,
        "radar_hash": RADAR_HASH,
        "synthesis_hash": NEWS_HASH,
    }


def _payload(summary: str = "Frozen evidence requires human review.") -> dict[str, object]:
    service = RecommendationAthenaSynthesisService()
    fingerprint = service.input_fingerprint(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        input_as_of=AS_OF,
        evidence_ids=("news-1", "risk-1"),
        covered_categories=("news", "factor_risk"),
    )
    return service.build(
        cycle_record=_cycle_record(),
        news_synthesis_record=_news_record(),
        model_output=AthenaSynthesisModelInput(
            model_provider="external-model-provider",
            model_name="athena-research-synthesis",
            model_version="2026-01",
            input_fingerprint=fingerprint,
            generated_at=AS_OF + timedelta(minutes=1),
            summary=summary,
            rationale="All frozen Radar evidence is referenced without assigning investment probability.",
            uncertainties=("The eventual operating impact remains uncertain.",),
            evidence_ids=("news-1", "risk-1"),
        ),
    ).to_api_dict()


def test_athena_synthesis_repository_round_trips_and_is_idempotent(tmp_path: Path) -> None:
    repository = RecommendationAthenaSynthesisRepository(
        AthenaDatabase(tmp_path / "athena-synthesis.db")
    )
    payload = _payload()

    first = repository.append(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        synthesis_payload=payload,
    )
    second = repository.append(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        synthesis_payload=payload,
    )
    loaded = repository.get_by_cycle_hash(cycle_hash=CYCLE_HASH)

    assert first["synthesis_hash"] == second["synthesis_hash"]
    assert loaded["synthesis_hash"] == first["synthesis_hash"]
    assert loaded["package"]["synthesis"] == payload
    assert loaded["news_synthesis_hash"] == NEWS_HASH


def test_athena_synthesis_repository_blocks_retrospective_model_shopping(tmp_path: Path) -> None:
    repository = RecommendationAthenaSynthesisRepository(
        AthenaDatabase(tmp_path / "athena-synthesis.db")
    )
    repository.append(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        synthesis_payload=_payload(),
    )

    with pytest.raises(ValueError, match="selección retrospectiva"):
        repository.append(
            cycle_hash=CYCLE_HASH,
            radar_hash=RADAR_HASH,
            news_synthesis_hash=NEWS_HASH,
            synthesis_payload=_payload("A different retrospective narrative must be rejected."),
        )


def test_athena_synthesis_repository_detects_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena-synthesis.db")
    repository = RecommendationAthenaSynthesisRepository(database)
    record = repository.append(
        cycle_hash=CYCLE_HASH,
        radar_hash=RADAR_HASH,
        news_synthesis_hash=NEWS_HASH,
        synthesis_payload=_payload(),
    )

    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_research_syntheses SET synthesis_hash = ? WHERE id = ?",
            ("0" * 64, record["id"]),
        )

    with pytest.raises(ValueError, match="synthesis_hash"):
        repository.get_by_cycle_hash(cycle_hash=CYCLE_HASH)


def test_athena_synthesis_repository_rejects_safety_flag_escalation(tmp_path: Path) -> None:
    repository = RecommendationAthenaSynthesisRepository(
        AthenaDatabase(tmp_path / "athena-synthesis.db")
    )
    payload = _payload()
    payload["automaticTrading"] = True

    with pytest.raises(ValueError, match="automaticTrading=false"):
        repository.append(
            cycle_hash=CYCLE_HASH,
            radar_hash=RADAR_HASH,
            news_synthesis_hash=NEWS_HASH,
            synthesis_payload=payload,
        )
