from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarCandidateResult,
    AthenaRadarEvidenceInput,
    AthenaRadarResult,
    RecommendationAthenaRadarService,
)
from app.services.recommendation_devils_advocate_service import (
    DevilsAdvocateEvidenceInput,
    RecommendationDevilsAdvocateService,
)
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)
from app.services.recommendation_professional_research_cycle_service import (
    RecommendationProfessionalResearchCycleService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


def _journal_and_devil():
    journal = RecommendationInvestmentJournalService().freeze_snapshot(
        journal_id="journal-aapl",
        revision_id="revision-1",
        symbol="AAPL",
        recorded_at=AVAILABLE_AT,
        as_of=AS_OF,
        thesis="Frozen thesis before outcome evidence.",
        references=(
            InvestmentJournalReferenceInput(
                reference_id="journal-ref-1",
                kind="assumption",
                available_at=AVAILABLE_AT - timedelta(minutes=1),
                source="athena-test",
                source_ref="urn:journal:1",
            ),
        ),
    )
    devil = RecommendationDevilsAdvocateService().review(
        journal_id=journal.journal_id,
        revision_id=journal.revision_id,
        snapshot_hash=journal.snapshot_hash,
        symbol="AAPL",
        as_of=AS_OF,
        evidence=(
            DevilsAdvocateEvidenceInput(
                evidence_id="devil-1",
                kind="alternative_explanation",
                claim="Alternative explanation requires human review.",
                strength="material",
                available_at=AVAILABLE_AT,
                source="athena-test",
                source_ref="urn:devil:1",
            ),
        ),
    )
    return journal, devil


def _bind(radar: AthenaRadarResult):
    journal, devil = _journal_and_devil()
    return RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl",
        radar=radar,
        journal=journal,
        devils_advocate=devil,
    )


def test_professional_cycle_accepts_only_radar_that_revalidates_canonically() -> None:
    evidence = AthenaRadarEvidenceInput(
        evidence_id="radar-1",
        category="thesis_invalidation",
        urgency="material",
        summary="Material research question.",
        available_at=AVAILABLE_AT,
        source="athena-test",
        source_ref="urn:radar:1",
    )
    radar = RecommendationAthenaRadarService().build(
        as_of=AS_OF,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                evidence=(evidence,),
            ),
        ),
    )

    result = _bind(radar).to_api_dict()

    assert result["researchUrgency"] == "material"
    assert result["policy"]["provenance"].startswith("radar_is_revalidated_canonically")
    assert result["policy"]["automaticTrading"] is False
    assert result["productionEligible"] is False


def test_professional_cycle_rejects_manually_forged_research_urgency() -> None:
    evidence = AthenaRadarEvidenceInput(
        evidence_id="radar-1",
        category="thesis_invalidation",
        urgency="routine",
        summary="Routine evidence cannot justify critical urgency.",
        available_at=AVAILABLE_AT,
        source="athena-test",
        source_ref="urn:radar:1",
    )
    forged = AthenaRadarResult(
        as_of=AS_OF.isoformat(),
        candidates=(
            AthenaRadarCandidateResult(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                research_urgency="critical",
                evidence=(evidence,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="resultado canónico recalculado"):
        _bind(forged)


def test_professional_cycle_rejects_forged_news_without_structured_provenance() -> None:
    forged_news = AthenaRadarEvidenceInput(
        evidence_id="news-1",
        category="news",
        urgency="material",
        summary="News supplied directly to a forged Radar result.",
        available_at=AVAILABLE_AT,
        source="news",
        source_ref="https://example.com/story",
        provider=None,
        publisher=None,
        published_at=None,
    )
    forged = AthenaRadarResult(
        as_of=AS_OF.isoformat(),
        candidates=(
            AthenaRadarCandidateResult(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                research_urgency="material",
                evidence=(forged_news,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="requiere provider explícito"):
        _bind(forged)


def test_professional_cycle_rejects_forged_investors_without_structured_provenance() -> None:
    forged_investor = AthenaRadarEvidenceInput(
        evidence_id="investor-1",
        category="investors",
        urgency="material",
        summary="Investor evidence supplied without primary-source provenance.",
        available_at=AVAILABLE_AT,
        source="investors",
        source_ref="https://example.com/filing",
        provider="issuer_ir",
        publisher=None,
        published_at=AVAILABLE_AT - timedelta(minutes=10),
    )
    forged = AthenaRadarResult(
        as_of=AS_OF.isoformat(),
        candidates=(
            AthenaRadarCandidateResult(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                research_urgency="material",
                evidence=(forged_investor,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="publisher/primary source explícito"):
        _bind(forged)


def test_professional_cycle_rejects_forged_radar_with_fmp_provenance() -> None:
    forbidden = AthenaRadarEvidenceInput(
        evidence_id="radar-fmp",
        category="data_quality",
        urgency="routine",
        summary="Forbidden source must not cross the professional-cycle boundary.",
        available_at=AVAILABLE_AT,
        source="Financial Modeling Prep",
        source_ref="https://financialmodelingprep.com/example",
    )
    forged = AthenaRadarResult(
        as_of=AS_OF.isoformat(),
        candidates=(
            AthenaRadarCandidateResult(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                research_urgency="routine",
                evidence=(forbidden,),
            ),
        ),
    )

    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        _bind(forged)
