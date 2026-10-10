from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_investors_synthesis_service import (
    RecommendationInvestorsSynthesisService,
)


def test_investors_synthesis_rejects_fabricated_radar_result() -> None:
    as_of = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
    available_at = as_of - timedelta(hours=1)
    radar = RecommendationAthenaRadarService().build(
        as_of=as_of,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                evidence=(
                    AthenaRadarEvidenceInput(
                        evidence_id="b" * 64,
                        category="investors",
                        urgency="material",
                        summary="Material filing.",
                        available_at=available_at,
                        source="SEC",
                        source_ref="https://www.sec.gov/Archives/example-10q.htm",
                        provider="sec_edgar",
                        publisher="SEC",
                        published_at=available_at - timedelta(minutes=15),
                    ),
                ),
            ),
        ),
    )
    fabricated_candidate = replace(radar.candidates[0], research_urgency="critical")
    fabricated = replace(radar, candidates=(fabricated_candidate,))

    with pytest.raises(ValueError, match="ATHENA Radar canónico"):
        RecommendationInvestorsSynthesisService().build(
            radar_result=fabricated,
            assessments=tuple(),
        )
