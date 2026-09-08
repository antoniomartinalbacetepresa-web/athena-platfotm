from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_research_outcome_attribution as outcome_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_professional_research_cycle_repository import (
    RecommendationProfessionalResearchCycleRepository,
)
from app.repositories.recommendation_research_outcome_attribution_repository import (
    RecommendationResearchOutcomeAttributionRepository,
)
from app.services.recommendation_athena_radar_service import (
    AthenaRadarCandidateInput,
    AthenaRadarEvidenceInput,
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
from app.services.recommendation_performance_attribution_service import (
    AttributionEvidence,
    FactorContributionEvidence,
    RecommendationPerformanceAttributionInput,
    RecommendationPerformanceAttributionService,
)
from app.services.recommendation_professional_research_cycle_service import (
    RecommendationProfessionalResearchCycleService,
)
from app.services.recommendation_research_outcome_attribution_service import (
    RecommendationResearchOutcomeAttributionService,
)


CYCLE_AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
PERIOD_START = CYCLE_AS_OF
PERIOD_END = CYCLE_AS_OF + timedelta(days=30)
OUTCOME_AS_OF = PERIOD_END + timedelta(hours=2)


def _cycle_record(repository: RecommendationProfessionalResearchCycleRepository):
    evidence_at = CYCLE_AS_OF - timedelta(hours=1)
    radar = RecommendationAthenaRadarService().build(
        as_of=CYCLE_AS_OF,
        candidates=(
            AthenaRadarCandidateInput(
                instrument_id="instrument-aapl",
                symbol="AAPL",
                evidence=(
                    AthenaRadarEvidenceInput(
                        evidence_id="radar-1",
                        category="thesis_invalidation",
                        urgency="material",
                        summary="Question requiring research.",
                        available_at=evidence_at,
                        source="athena-test",
                        source_ref="urn:radar:1",
                    ),
                ),
            ),
        ),
    )
    journal = RecommendationInvestmentJournalService().freeze_snapshot(
        journal_id="journal-aapl",
        revision_id="revision-1",
        symbol="AAPL",
        recorded_at=evidence_at,
        as_of=CYCLE_AS_OF,
        thesis="Frozen thesis before posterior outcome.",
        references=(
            InvestmentJournalReferenceInput(
                reference_id="journal-ref-1",
                kind="assumption",
                available_at=evidence_at - timedelta(minutes=1),
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
        as_of=CYCLE_AS_OF,
        evidence=(
            DevilsAdvocateEvidenceInput(
                evidence_id="devil-1",
                kind="alternative_explanation",
                claim="Alternative explanation requires review.",
                strength="material",
                available_at=evidence_at,
                source="athena-test",
                source_ref="urn:devil:1",
            ),
        ),
    )
    cycle = RecommendationProfessionalResearchCycleService().bind(
        instrument_id="instrument-aapl",
        radar=radar,
        journal=journal,
        devils_advocate=devil,
    )
    return repository.append(
        cycle_payload=cycle.to_api_dict(),
        radar_payload=radar.to_api_dict(),
        journal_payload=journal.to_api_dict(),
        devils_advocate_payload=devil.to_api_dict(),
    )


def _attribution(*, available_at: datetime = PERIOD_END + timedelta(minutes=1), source: str = "athena-outcome"):
    def ev(value: float, ref: str) -> AttributionEvidence:
        return AttributionEvidence(value=value, available_at=available_at, source=source, source_ref=ref)

    return RecommendationPerformanceAttributionService().evaluate(
        as_of=OUTCOME_AS_OF,
        item=RecommendationPerformanceAttributionInput(
            instrument_id="instrument-aapl",
            symbol="AAPL",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            total_return=ev(0.12, "urn:outcome:total"),
            market_contribution=ev(0.05, "urn:outcome:market"),
            fx_contribution=ev(0.01, "urn:outcome:fx"),
            factor_contributions=(
                FactorContributionEvidence(
                    factor="quality",
                    contribution=0.02,
                    available_at=available_at,
                    source=source,
                    source_ref="urn:outcome:quality",
                ),
            ),
        ),
    ).to_api_dict()


def _request(cycle_hash: str) -> tuple[str, dict[str, object]]:
    available = (PERIOD_END + timedelta(minutes=1)).isoformat()
    return cycle_hash, {
        "outcomeId": "30d-v1",
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": OUTCOME_AS_OF.isoformat(),
        "periodStart": PERIOD_START.isoformat(),
        "periodEnd": PERIOD_END.isoformat(),
        "totalReturn": {"value": 0.12, "availableAt": available, "source": "athena-outcome", "sourceRef": "urn:outcome:total"},
        "marketContribution": {"value": 0.05, "availableAt": available, "source": "athena-outcome", "sourceRef": "urn:outcome:market"},
        "fxContribution": {"value": 0.01, "availableAt": available, "source": "athena-outcome", "sourceRef": "urn:outcome:fx"},
        "factorContributions": [
            {"factor": "quality", "contribution": 0.02, "availableAt": available, "source": "athena-outcome", "sourceRef": "urn:outcome:quality"}
        ],
    }


def test_outcome_binds_posterior_attribution_to_exact_cycle(tmp_path: Path) -> None:
    cycle_repo = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "outcome.db"))
    cycle = _cycle_record(cycle_repo)
    result = RecommendationResearchOutcomeAttributionService().bind(
        outcome_id="30d-v1", cycle_record=cycle, attribution_payload=_attribution()
    )

    assert result["cycleHash"] == cycle["cycle_hash"]
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["isWeightingReady"] is False
    assert result["policy"]["automaticTrading"] is False
    assert result["policy"]["learning"] == "research_only_not_automatic_model_update"
    assert result["attribution"]["residualReturn"] == pytest.approx(0.04)


def test_outcome_rejects_period_before_frozen_cycle(tmp_path: Path) -> None:
    cycle_repo = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "pre-cycle.db"))
    cycle = _cycle_record(cycle_repo)
    payload = _attribution()
    payload["periodStart"] = (CYCLE_AS_OF - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="no puede comenzar antes"):
        RecommendationResearchOutcomeAttributionService().bind(
            outcome_id="bad-period", cycle_record=cycle, attribution_payload=payload
        )


def test_outcome_rejects_evidence_available_before_period_end(tmp_path: Path) -> None:
    cycle_repo = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "early-evidence.db"))
    cycle = _cycle_record(cycle_repo)
    with pytest.raises(ValueError, match="antes de cerrar el periodo"):
        RecommendationResearchOutcomeAttributionService().bind(
            outcome_id="early", cycle_record=cycle, attribution_payload=_attribution(available_at=PERIOD_END - timedelta(seconds=1))
        )


def test_outcome_rejects_identity_mismatch_and_fmp(tmp_path: Path) -> None:
    cycle_repo = RecommendationProfessionalResearchCycleRepository(AthenaDatabase(tmp_path / "identity.db"))
    cycle = _cycle_record(cycle_repo)
    mismatch = _attribution()
    mismatch["symbol"] = "MSFT"
    with pytest.raises(ValueError, match="symbol"):
        RecommendationResearchOutcomeAttributionService().bind(
            outcome_id="mismatch", cycle_record=cycle, attribution_payload=mismatch
        )
    with pytest.raises(ValueError, match="FMP/Financial Modeling Prep"):
        RecommendationResearchOutcomeAttributionService().bind(
            outcome_id="fmp", cycle_record=cycle, attribution_payload=_attribution(source="Financial Modeling Prep")
        )


def test_outcome_repository_is_idempotent_and_detects_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "persist.db")
    cycle_repo = RecommendationProfessionalResearchCycleRepository(database)
    cycle = _cycle_record(cycle_repo)
    payload = RecommendationResearchOutcomeAttributionService().bind(
        outcome_id="30d-v1", cycle_record=cycle, attribution_payload=_attribution()
    )
    repo = RecommendationResearchOutcomeAttributionRepository(database)
    first = repo.append(payload=payload)
    same = repo.append(payload=payload)
    assert same["outcome_hash"] == first["outcome_hash"]

    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM athena_research_outcome_attributions WHERE outcome_hash = ?",
            (first["outcome_hash"],),
        ).fetchone()
        stored = json.loads(str(row["payload_json"]))
        stored["attribution"]["residualReturn"] = 99.0
        connection.execute(
            "UPDATE athena_research_outcome_attributions SET payload_json = ? WHERE outcome_hash = ?",
            (json.dumps(stored, sort_keys=True, separators=(",", ":")), first["outcome_hash"]),
        )

    with pytest.raises(ValueError, match="outcomeHash canónico"):
        repo.get_by_hash(outcome_hash=first["outcome_hash"])


def test_outcome_api_persists_and_retrieves_verified_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = AthenaDatabase(tmp_path / "api.db")
    cycle_repo = RecommendationProfessionalResearchCycleRepository(database)
    cycle = _cycle_record(cycle_repo)
    outcome_repo = RecommendationResearchOutcomeAttributionRepository(database)
    monkeypatch.setattr(outcome_api, "cycle_repository", cycle_repo)
    monkeypatch.setattr(outcome_api, "outcome_repository", outcome_repo)
    client = TestClient(app)
    cycle_hash, request = _request(cycle["cycle_hash"])

    response = client.post(
        f"/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/outcome-attribution",
        json=request,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cycleHash"] == cycle_hash
    assert data["persistence"]["appendOnly"] is True
    assert data["persistence"]["tamperEvident"] is True
    assert data["policy"]["automaticTrading"] is False

    fetched = client.get(
        f"/api/v1/recommendations/professional-research/research-cycle/outcome-attribution/{data['outcomeHash']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["data"]["outcomeHash"] == data["outcomeHash"]


def test_outcome_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations/professional-research/research-cycle/{cycle_hash}/outcome-attribution" in paths
    assert "/api/v1/recommendations/professional-research/research-cycle/outcome-attribution/{outcome_hash}" in paths
