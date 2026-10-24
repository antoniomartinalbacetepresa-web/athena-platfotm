from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_news_synthesis_repository import (
    RecommendationNewsSynthesisRepository,
)
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_news_synthesis_service import (
    NewsModelAssessmentInput,
    RecommendationNewsSynthesisService,
)


def _dt(hour: int) -> datetime:
    return datetime(2026, 9, 13, hour, 0, tzinfo=timezone.utc)


def _synthesis(*, importance: str = "high") -> dict[str, object]:
    radar = RecommendationAthenaRadarService().build(
        as_of=_dt(10),
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="issuer:acme",
                symbol="ACME",
                evidence=(
                    AthenaRadarEvidenceInput(
                        evidence_id="news-1",
                        category="news",
                        urgency="material",
                        summary="Material issuer update.",
                        available_at=_dt(9),
                        source="news",
                        source_ref="https://example.com/news/1",
                        provider="google_news_rss",
                        publisher="Example Wire",
                        published_at=_dt(8),
                    ),
                ),
            ),
        ),
    )
    service = RecommendationNewsSynthesisService()
    candidate = radar.candidates[0]
    evidence = candidate.evidence[0]
    assessment = NewsModelAssessmentInput(
        evidence_id=evidence.evidence_id,
        model_provider="test-model-boundary",
        model_name="news-research-model",
        model_version="v1",
        input_fingerprint=service.evidence_fingerprint(
            instrument_id=candidate.instrument_id,
            symbol=candidate.symbol,
            evidence=evidence,
        ),
        generated_at=_dt(9),
        summary="The update changes near-term research priorities.",
        importance=importance,
        impact_direction="mixed",
        impact_magnitude=0.6,
        confidence=0.5,
    )
    return service.build(
        radar_result=radar,
        assessments=(assessment,),
        minimum_importance="high",
    ).to_api_dict()


def _repository(tmp_path: Path) -> RecommendationNewsSynthesisRepository:
    return RecommendationNewsSynthesisRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )


def test_persists_cycle_bound_synthesis_and_reads_it_back(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    cycle_hash = "1" * 64
    radar_hash = "2" * 64
    payload = _synthesis()

    stored = repository.append(
        cycle_hash=cycle_hash,
        radar_hash=radar_hash,
        synthesis_payload=payload,
    )
    loaded = repository.get_by_cycle_hash(cycle_hash=cycle_hash)

    assert stored["cycle_hash"] == cycle_hash
    assert stored["radar_hash"] == radar_hash
    assert len(stored["synthesis_hash"]) == 64
    assert loaded["synthesis_hash"] == stored["synthesis_hash"]
    assert loaded["package"]["synthesis"] == payload


def test_same_exact_artifact_is_idempotent(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    payload = _synthesis()

    first = repository.append(
        cycle_hash="1" * 64,
        radar_hash="2" * 64,
        synthesis_payload=payload,
    )
    second = repository.append(
        cycle_hash="1" * 64,
        radar_hash="2" * 64,
        synthesis_payload=payload,
    )

    assert first["id"] == second["id"]
    assert first["synthesis_hash"] == second["synthesis_hash"]


def test_rejects_model_shopping_for_same_cycle(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.append(
        cycle_hash="1" * 64,
        radar_hash="2" * 64,
        synthesis_payload=_synthesis(importance="high"),
    )

    with pytest.raises(ValueError, match="selección retrospectiva"):
        repository.append(
            cycle_hash="1" * 64,
            radar_hash="2" * 64,
            synthesis_payload=_synthesis(importance="critical"),
        )


def test_rejects_payload_that_drops_complete_assessment_audit(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    payload = _synthesis()
    payload["assessments"] = []

    with pytest.raises(ValueError, match="assessments completos"):
        repository.append(
            cycle_hash="1" * 64,
            radar_hash="2" * 64,
            synthesis_payload=payload,
        )


def test_rejects_fmp_in_model_or_evidence_provider(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    payload = _synthesis()
    payload["assessments"][0]["modelProvider"] = "FMP"
    payload["items"][0]["modelProvider"] = "FMP"

    with pytest.raises(ValueError, match="FMP"):
        repository.append(
            cycle_hash="1" * 64,
            radar_hash="2" * 64,
            synthesis_payload=payload,
        )


def test_detects_persisted_package_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationNewsSynthesisRepository(database)
    stored = repository.append(
        cycle_hash="1" * 64,
        radar_hash="2" * 64,
        synthesis_payload=_synthesis(),
    )

    package = dict(stored["package"])
    synthesis = dict(package["synthesis"])
    synthesis["minimumImportance"] = "critical"
    package["synthesis"] = synthesis
    with database.connect() as connection:
        connection.execute(
            "UPDATE athena_news_syntheses SET package_json = ? WHERE cycle_hash = ?",
            (
                json.dumps(package, sort_keys=True, separators=(",", ":")),
                "1" * 64,
            ),
        )

    with pytest.raises(ValueError, match="synthesis_hash"):
        repository.get_by_cycle_hash(cycle_hash="1" * 64)


def test_rejects_filtered_item_not_identical_to_audited_assessment(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    payload = _synthesis()
    payload["items"][0] = dict(payload["items"][0])
    payload["items"][0]["summary"] = "Altered visible summary."

    with pytest.raises(ValueError, match="exactamente"):
        repository.append(
            cycle_hash="1" * 64,
            radar_hash="2" * 64,
            synthesis_payload=payload,
        )
