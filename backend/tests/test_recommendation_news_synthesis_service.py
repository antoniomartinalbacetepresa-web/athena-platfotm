from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarCandidateResult,
    AthenaRadarEvidenceInput,
    AthenaRadarResult,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_news_synthesis_service import (
    NewsModelAssessmentInput,
    RecommendationNewsSynthesisService,
)


def _dt(hour: int) -> datetime:
    return datetime(2026, 9, 13, hour, 0, tzinfo=timezone.utc)


def _radar(*, second: bool = False) -> AthenaRadarResult:
    evidences = [
        AthenaRadarEvidenceInput(
            evidence_id="news-1",
            category="news",
            urgency="material",
            summary="Issuer announced a material operating update.",
            available_at=_dt(9),
            source="news",
            source_ref="https://example.com/news/1",
            provider="google_news_rss",
            publisher="Example Wire",
            published_at=_dt(8),
        )
    ]
    if second:
        evidences.append(
            AthenaRadarEvidenceInput(
                evidence_id="news-2",
                category="news",
                urgency="routine",
                summary="Issuer published a routine product update.",
                available_at=_dt(9),
                source="news",
                source_ref="https://example.com/news/2",
                provider="google_news_rss",
                publisher="Example Journal",
                published_at=_dt(8),
            )
        )
    return RecommendationAthenaRadarService().build(
        as_of=_dt(10),
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="issuer:acme",
                symbol="ACME",
                evidence=tuple(evidences),
            ),
        ),
    )


def _assessment(
    service: RecommendationNewsSynthesisService,
    radar: AthenaRadarResult,
    evidence_id: str = "news-1",
    **overrides: object,
) -> NewsModelAssessmentInput:
    candidate = radar.candidates[0]
    evidence = next(item for item in candidate.evidence if item.evidence_id == evidence_id)
    values = {
        "evidence_id": evidence_id,
        "model_provider": "openai-compatible-test-boundary",
        "model_name": "news-research-model",
        "model_version": "2026-09-13",
        "input_fingerprint": service.evidence_fingerprint(
            instrument_id=candidate.instrument_id,
            symbol=candidate.symbol,
            evidence=evidence,
        ),
        "generated_at": _dt(9),
        "summary": "The operating update may materially change near-term research priorities.",
        "importance": "high",
        "impact_direction": "mixed",
        "impact_magnitude": 0.7,
        "confidence": 0.6,
    }
    values.update(overrides)
    return NewsModelAssessmentInput(**values)


def test_validates_model_provenance_and_keeps_synthesis_non_advisory() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    result = service.build(
        radar_result=radar,
        assessments=(_assessment(service, radar),),
    )

    assert result.assessed_count == 1
    assert result.included_count == 1
    item = result.items[0]
    assert item.evidence_provider == "google_news_rss"
    assert item.publisher == "Example Wire"
    assert item.source_ref == "https://example.com/news/1"
    assert item.importance == "high"
    assert item.impact_direction == "mixed"
    assert len(item.input_fingerprint) == 64
    assert len(item.assessment_fingerprint) == 64

    api = result.to_api_dict()
    assert api["status"] == "validated_external_model_output"
    assert api["modelExecutionVerified"] is False
    assert api["productionTruthClaimed"] is False
    assert api["independentCorroborationClaimed"] is False
    assert api["recommendationInfluence"] is False
    assert api["automaticScoring"] is False
    assert api["automaticTrading"] is False


def test_filters_by_importance_without_hiding_assessment_coverage() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar(second=True)
    assessments = (
        _assessment(service, radar, "news-1", importance="critical"),
        _assessment(
            service,
            radar,
            "news-2",
            importance="low",
            impact_magnitude=0.1,
        ),
    )

    result = service.build(
        radar_result=radar,
        assessments=assessments,
        minimum_importance="high",
    )

    assert result.assessed_count == 2
    assert result.included_count == 1
    assert result.excluded_count == 1
    assert [item.evidence_id for item in result.items] == ["news-1"]


def test_rejects_fingerprint_mismatch() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    assessment = _assessment(service, radar, input_fingerprint="0" * 64)

    with pytest.raises(ValueError, match="input_fingerprint"):
        service.build(radar_result=radar, assessments=(assessment,))


@pytest.mark.parametrize(
    ("generated_at", "message"),
    [
        (_dt(8), "disponibilidad PIT"),
        (datetime(2026, 9, 13, 11, tzinfo=timezone.utc), "posterior"),
    ],
)
def test_rejects_lookahead_or_preavailability_model_output(
    generated_at: datetime, message: str
) -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    assessment = _assessment(service, radar, generated_at=generated_at)

    with pytest.raises(ValueError, match=message):
        service.build(radar_result=radar, assessments=(assessment,))


def test_requires_exactly_one_assessment_per_news_evidence() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar(second=True)

    with pytest.raises(ValueError, match="exactamente una"):
        service.build(
            radar_result=radar,
            assessments=(_assessment(service, radar, "news-1"),),
        )


def test_rejects_duplicate_assessment_ids() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar(second=True)
    first = _assessment(service, radar, "news-1")

    with pytest.raises(ValueError, match="repetirse"):
        service.build(radar_result=radar, assessments=(first, first))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", float("nan")),
        ("confidence", 1.01),
        ("impact_magnitude", -0.01),
        ("impact_magnitude", float("inf")),
    ],
)
def test_rejects_invalid_numeric_model_claims(field: str, value: float) -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    assessment = _assessment(service, radar, **{field: value})

    with pytest.raises(ValueError, match="entre 0 y 1"):
        service.build(radar_result=radar, assessments=(assessment,))


def test_rejects_fmp_as_model_provider() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    assessment = _assessment(service, radar, model_provider="FMP")

    with pytest.raises(ValueError, match="FMP"):
        service.build(radar_result=radar, assessments=(assessment,))


def test_rejects_manually_fabricated_radar_that_bypasses_news_provenance() -> None:
    service = RecommendationNewsSynthesisService()
    evidence = AthenaRadarEvidenceInput(
        evidence_id="news-bypass",
        category="news",
        urgency="material",
        summary="Unvalidated external evidence.",
        available_at=_dt(9),
        source="news",
        source_ref="https://example.com/bypass",
    )
    fabricated = AthenaRadarResult(
        as_of=_dt(10).isoformat(),
        candidates=(
            AthenaRadarCandidateResult(
                instrument_id="issuer:acme",
                symbol="ACME",
                research_urgency="material",
                evidence=(evidence,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="provider"):
        service.build(radar_result=fabricated, assessments=())


def test_assessment_fingerprint_is_deterministic() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    assessment = _assessment(service, radar)

    first = service.build(radar_result=radar, assessments=(assessment,))
    second = service.build(radar_result=radar, assessments=(assessment,))

    assert first.items[0].assessment_fingerprint == second.items[0].assessment_fingerprint


def test_rejects_noncanonical_radar_urgency_even_with_valid_evidence() -> None:
    service = RecommendationNewsSynthesisService()
    radar = _radar()
    candidate = radar.candidates[0]
    fabricated_candidate = replace(candidate, research_urgency="critical")
    fabricated = replace(radar, candidates=(fabricated_candidate,))

    with pytest.raises(ValueError, match="canónico"):
        service.build(
            radar_result=fabricated,
            assessments=(_assessment(service, radar),),
        )
