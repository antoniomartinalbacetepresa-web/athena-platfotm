from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_professional_research_cycle as cycle_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
RECORDED_AT = AS_OF - timedelta(hours=1)


def _payload(*, journal_source: str = "athena-test", contradictory_kind: str = "alternative_explanation") -> dict[str, object]:
    return {
        "instrumentId": "instrument-aapl",
        "symbol": "AAPL",
        "asOf": AS_OF.isoformat(),
        "radarEvidence": [
            {
                "evidenceId": "radar-1",
                "category": "thesis_invalidation",
                "urgency": "material",
                "summary": "Material research question.",
                "availableAt": RECORDED_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:radar:1",
            }
        ],
        "journalId": "journal-aapl-side-effect",
        "revisionId": "revision-1",
        "recordedAt": RECORDED_AT.isoformat(),
        "thesis": "Frozen thesis before outcome evidence.",
        "journalReferences": [
            {
                "referenceId": "journal-ref-1",
                "kind": "assumption",
                "availableAt": (RECORDED_AT - timedelta(minutes=1)).isoformat(),
                "source": journal_source,
                "sourceRef": "urn:journal:1",
            }
        ],
        "priorSnapshotHash": None,
        "contradictoryEvidence": [
            {
                "evidenceId": "devil-1",
                "kind": contradictory_kind,
                "claim": "Alternative explanation requires human review.",
                "strength": "material",
                "availableAt": RECORDED_AT.isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:devil:1",
            }
        ],
    }


def _repository(tmp_path: Path, name: str) -> RecommendationInvestmentJournalRepository:
    return RecommendationInvestmentJournalRepository(AthenaDatabase(tmp_path / name))


def test_fmp_rejection_happens_before_append_only_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path, "cycle-fmp.db")
    monkeypatch.setattr(cycle_api, "journal_repository", repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(journal_source="Financial Modeling Prep"),
    )

    assert response.status_code == 400
    assert "FMP/Financial Modeling Prep" in response.json()["detail"]
    with pytest.raises(ValueError, match="No existe un journal"):
        repository.verify_lineage(journal_id="journal-aapl-side-effect")


def test_invalid_devils_advocate_evidence_does_not_leave_partial_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path, "cycle-devil.db")
    monkeypatch.setattr(cycle_api, "journal_repository", repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations/professional-research/research-cycle",
        json=_payload(contradictory_kind="unsupported_kind"),
    )

    assert response.status_code == 400
    with pytest.raises(ValueError, match="No existe un journal"):
        repository.verify_lineage(journal_id="journal-aapl-side-effect")
