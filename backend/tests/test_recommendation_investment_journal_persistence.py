from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_investment_journal as journal_api
from app.database.athena_database import AthenaDatabase
from app.main import app
from app.repositories.recommendation_investment_journal_repository import (
    RecommendationInvestmentJournalRepository,
)
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
RECORDED_AT = datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)


def _repository(tmp_path: Path) -> RecommendationInvestmentJournalRepository:
    return RecommendationInvestmentJournalRepository(
        AthenaDatabase(tmp_path / "investment-journal.db")
    )


def _snapshot(
    *,
    revision_id: str = "revision-1",
    symbol: str = "AAPL",
    recorded_at: datetime = RECORDED_AT,
    thesis: str = "Durable thesis frozen before outcome evidence.",
    prior_snapshot_hash: str | None = None,
):
    return RecommendationInvestmentJournalService().freeze_snapshot(
        journal_id="journal-aapl-1",
        revision_id=revision_id,
        symbol=symbol,
        recorded_at=recorded_at,
        as_of=AS_OF,
        thesis=thesis,
        references=(
            InvestmentJournalReferenceInput(
                reference_id=f"assumption-{revision_id}",
                kind="assumption",
                available_at=recorded_at - timedelta(minutes=5),
                source="athena-test",
                source_ref=f"urn:test:{revision_id}",
            ),
        ),
        prior_snapshot_hash=prior_snapshot_hash,
    )


def _api_payload(
    *,
    revision_id: str = "revision-1",
    recorded_at: datetime = RECORDED_AT,
    prior_snapshot_hash: str | None = None,
) -> dict[str, object]:
    return {
        "journalId": "journal-aapl-1",
        "revisionId": revision_id,
        "symbol": "AAPL",
        "recordedAt": recorded_at.isoformat(),
        "asOf": AS_OF.isoformat(),
        "thesis": f"Frozen thesis for {revision_id}.",
        "references": [
            {
                "referenceId": f"assumption-{revision_id}",
                "kind": "assumption",
                "availableAt": (recorded_at - timedelta(minutes=5)).isoformat(),
                "source": "athena-test",
                "sourceRef": f"urn:test:{revision_id}",
            }
        ],
        "priorSnapshotHash": prior_snapshot_hash,
    }


def test_repository_appends_and_verifies_exact_hash_lineage(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _snapshot()
    first_record = repository.append(snapshot=first)
    second = _snapshot(
        revision_id="revision-2",
        recorded_at=RECORDED_AT + timedelta(hours=1),
        prior_snapshot_hash=first.snapshot_hash,
    )
    second_record = repository.append(snapshot=second)

    lineage = repository.verify_lineage(journal_id="journal-aapl-1")

    assert first_record["snapshot_hash"] == first.snapshot_hash
    assert second_record["prior_snapshot_hash"] == first.snapshot_hash
    assert second_record["snapshot_hash"] == second.snapshot_hash
    assert lineage["status"] == "lineage_verified"
    assert lineage["revisionCount"] == 2
    assert lineage["headSnapshotHash"] == second.snapshot_hash
    assert lineage["advisoryStatus"] == "no_advice"
    assert lineage["productionEligible"] is False
    assert lineage["isWeightingReady"] is False
    assert lineage["policy"]["appendOnly"] is True
    assert lineage["policy"]["automaticTrading"] is False
    assert lineage["policy"]["automaticProductionPromotion"] is False


def test_repository_is_idempotent_for_same_revision_and_hash(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    snapshot = _snapshot()

    first = repository.append(snapshot=snapshot)
    second = repository.append(snapshot=snapshot)

    assert first["id"] == second["id"]
    assert repository.verify_lineage(journal_id="journal-aapl-1")["revisionCount"] == 1


def test_repository_rejects_first_revision_with_prior_hash(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="primera revisión"):
        repository.append(snapshot=_snapshot(prior_snapshot_hash="0" * 64))


def test_repository_rejects_revision_that_does_not_link_to_current_head(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.append(snapshot=_snapshot())

    with pytest.raises(ValueError, match="head persistido"):
        repository.append(
            snapshot=_snapshot(
                revision_id="revision-2",
                recorded_at=RECORDED_AT + timedelta(hours=1),
                prior_snapshot_hash="0" * 64,
            )
        )


def test_repository_rejects_rewriting_existing_revision(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.append(snapshot=_snapshot())

    with pytest.raises(ValueError, match="inmutables"):
        repository.append(snapshot=_snapshot(thesis="Retrospectively rewritten thesis."))


def test_repository_rejects_symbol_change_inside_same_journal(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _snapshot()
    repository.append(snapshot=first)

    with pytest.raises(ValueError, match="símbolo no puede cambiar"):
        repository.append(
            snapshot=_snapshot(
                revision_id="revision-2",
                symbol="MSFT",
                recorded_at=RECORDED_AT + timedelta(hours=1),
                prior_snapshot_hash=first.snapshot_hash,
            )
        )


def test_repository_rejects_time_regression(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    first = _snapshot(recorded_at=RECORDED_AT + timedelta(hours=1))
    repository.append(snapshot=first)

    with pytest.raises(ValueError, match="no puede retroceder"):
        repository.append(
            snapshot=_snapshot(
                revision_id="revision-2",
                recorded_at=RECORDED_AT,
                prior_snapshot_hash=first.snapshot_hash,
            )
        )


def test_verify_lineage_detects_persisted_payload_tampering(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    snapshot = _snapshot()
    repository.append(snapshot=snapshot)

    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT snapshot_json FROM athena_investment_journal_snapshots WHERE journal_id = ?",
            ("journal-aapl-1",),
        ).fetchone()
        payload = json.loads(str(row["snapshot_json"]))
        payload["thesis"] = "Tampered after persistence."
        connection.execute(
            "UPDATE athena_investment_journal_snapshots SET snapshot_json = ? WHERE journal_id = ?",
            (json.dumps(payload), "journal-aapl-1"),
        )

    with pytest.raises(ValueError, match="snapshot_hash canónico"):
        repository.verify_lineage(journal_id="journal-aapl-1")


def test_persisted_snapshot_api_and_lineage_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setattr(journal_api, "investment_journal_repository", repository)
    client = TestClient(app)

    first_response = client.post(
        "/api/v1/recommendations/professional-research/investment-journal/persisted-snapshot",
        json=_api_payload(),
    )
    assert first_response.status_code == 200
    first_data = first_response.json()["data"]
    first_hash = first_data["snapshot"]["snapshotHash"]
    assert first_data["persistence"]["revisionCount"] == 1
    assert first_data["persistence"]["policy"]["appendOnly"] is True
    assert first_data["snapshot"]["policy"]["persistentAppendOnlyStorage"] is False

    second_response = client.post(
        "/api/v1/recommendations/professional-research/investment-journal/persisted-snapshot",
        json=_api_payload(
            revision_id="revision-2",
            recorded_at=RECORDED_AT + timedelta(hours=1),
            prior_snapshot_hash=first_hash,
        ),
    )
    assert second_response.status_code == 200
    second_data = second_response.json()["data"]
    assert second_data["persistence"]["revisionCount"] == 2
    assert second_data["persistence"]["headSnapshotHash"] == second_data["snapshot"]["snapshotHash"]

    lineage_response = client.get(
        "/api/v1/recommendations/professional-research/investment-journal/journal-aapl-1/lineage"
    )
    assert lineage_response.status_code == 200
    assert lineage_response.json()["data"]["revisionCount"] == 2


def test_persisted_snapshot_api_rejects_broken_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(tmp_path)
    monkeypatch.setattr(journal_api, "investment_journal_repository", repository)
    client = TestClient(app)
    first = client.post(
        "/api/v1/recommendations/professional-research/investment-journal/persisted-snapshot",
        json=_api_payload(),
    )
    assert first.status_code == 200

    response = client.post(
        "/api/v1/recommendations/professional-research/investment-journal/persisted-snapshot",
        json=_api_payload(
            revision_id="revision-2",
            recorded_at=RECORDED_AT + timedelta(hours=1),
            prior_snapshot_hash="0" * 64,
        ),
    )

    assert response.status_code == 400
    assert "head persistido" in response.json()["detail"]


class _UnsafeRepository:
    def append(self, *, snapshot):
        return {"snapshot_hash": snapshot.snapshot_hash}

    def verify_lineage(self, *, journal_id: str):
        return {
            "status": "lineage_verified",
            "journalId": journal_id,
            "symbol": "AAPL",
            "revisionCount": 1,
            "headSnapshotHash": "0" * 64,
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "policy": {
                "appendOnly": True,
                "lineage": "every_revision_links_to_exact_previous_persisted_snapshot_hash",
                "automaticTrading": True,
                "automaticProductionPromotion": False,
            },
        }


def test_persisted_snapshot_api_fails_closed_on_automatic_trading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_api, "investment_journal_repository", _UnsafeRepository())

    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/investment-journal/persisted-snapshot",
        json=_api_payload(),
    )

    assert response.status_code == 500
    assert "automatismos prohibidos" in response.json()["detail"]
