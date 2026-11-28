from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.recommendation_investment_journal as journal_api
from app.main import app
from app.services.recommendation_investment_journal_service import (
    InvestmentJournalReferenceInput,
    RecommendationInvestmentJournalService,
)


AS_OF = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
RECORDED_AT = datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc)


def _reference(
    reference_id: str = "assumption-1",
    *,
    kind: str = "assumption",
    available_at: datetime | None = None,
    source: str = "athena-test",
    source_ref: str = "urn:test:assumption-1",
) -> InvestmentJournalReferenceInput:
    return InvestmentJournalReferenceInput(
        reference_id=reference_id,
        kind=kind,
        available_at=available_at or (RECORDED_AT - timedelta(hours=1)),
        source=source,
        source_ref=source_ref,
    )


def _freeze(**overrides: object):
    service = RecommendationInvestmentJournalService()
    payload = {
        "journal_id": "journal-aapl-1",
        "revision_id": "revision-1",
        "symbol": "aapl",
        "recorded_at": RECORDED_AT,
        "as_of": AS_OF,
        "thesis": "Revenue durability must be supported by evidence known before the outcome.",
        "references": (
            _reference("catalyst-1", kind="catalyst", source_ref="urn:test:catalyst-1"),
            _reference("assumption-1", kind="assumption", source_ref="urn:test:assumption-1"),
        ),
        "prior_snapshot_hash": None,
    }
    payload.update(overrides)
    return service.freeze_snapshot(**payload)


def _api_payload() -> dict[str, object]:
    return {
        "journalId": "journal-aapl-1",
        "revisionId": "revision-1",
        "symbol": "AAPL",
        "recordedAt": RECORDED_AT.isoformat(),
        "asOf": AS_OF.isoformat(),
        "thesis": "Evidence available before the outcome defines the frozen thesis.",
        "references": [
            {
                "referenceId": "assumption-1",
                "kind": "assumption",
                "availableAt": (RECORDED_AT - timedelta(hours=1)).isoformat(),
                "source": "athena-test",
                "sourceRef": "urn:test:assumption-1",
            }
        ],
    }


def test_snapshot_is_deterministic_and_preserves_safety_contract() -> None:
    first = _freeze()
    second = _freeze(references=tuple(reversed(first.references)))

    assert first.snapshot_hash == second.snapshot_hash
    assert first.symbol == "AAPL"
    assert len(first.snapshot_hash) == 64
    payload = first.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["persistentAppendOnlyStorage"] is False
    assert payload["policy"]["hindsight"] == "snapshot_records_only_evidence_available_when_recorded"
    assert [item["referenceId"] for item in payload["references"]] == ["assumption-1", "catalyst-1"]


def test_snapshot_hash_changes_when_frozen_thesis_or_provenance_changes() -> None:
    baseline = _freeze()
    changed_thesis = _freeze(thesis="Different thesis known at the same point in time.")
    changed_source_ref = _freeze(
        references=(
            _reference("catalyst-1", kind="catalyst", source_ref="urn:test:catalyst-1"),
            _reference("assumption-1", kind="assumption", source_ref="urn:test:changed"),
        )
    )

    assert baseline.snapshot_hash != changed_thesis.snapshot_hash
    assert baseline.snapshot_hash != changed_source_ref.snapshot_hash


def test_rejects_reference_lookahead() -> None:
    with pytest.raises(ValueError, match="posterior a recorded_at"):
        _freeze(references=(_reference(available_at=RECORDED_AT + timedelta(seconds=1)),))


def test_rejects_recording_after_as_of() -> None:
    with pytest.raises(ValueError, match="posterior a as_of"):
        _freeze(recorded_at=AS_OF + timedelta(seconds=1))


@pytest.mark.parametrize(
    "field,value",
    [
        ("recorded_at", RECORDED_AT.replace(tzinfo=None)),
        ("as_of", AS_OF.replace(tzinfo=None)),
    ],
)
def test_rejects_naive_snapshot_timestamps(field: str, value: datetime) -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        _freeze(**{field: value})


def test_rejects_naive_reference_timestamp() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        _freeze(references=(_reference(available_at=RECORDED_AT.replace(tzinfo=None)),))


def test_rejects_duplicate_reference_identity() -> None:
    with pytest.raises(ValueError, match="reference_id no puede repetirse"):
        _freeze(references=(_reference("same"), _reference("same")))


def test_rejects_unsupported_reference_kind() -> None:
    with pytest.raises(ValueError, match="kind no está soportado"):
        _freeze(references=(_reference(kind="price_target"),))


@pytest.mark.parametrize("field", ["source", "source_ref"])
def test_rejects_missing_reference_provenance(field: str) -> None:
    kwargs = {field: " "}
    with pytest.raises(ValueError, match="obligatorio"):
        _freeze(references=(_reference(**kwargs),))


@pytest.mark.parametrize("value", ["", "abc", "g" * 64, "0" * 63, "0" * 65])
def test_rejects_invalid_prior_snapshot_hash(value: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _freeze(prior_snapshot_hash=value)


def test_accepts_explicit_prior_snapshot_hash_without_claiming_persistence() -> None:
    previous = _freeze()
    current = _freeze(revision_id="revision-2", prior_snapshot_hash=previous.snapshot_hash)
    payload = current.to_api_dict()

    assert payload["priorSnapshotHash"] == previous.snapshot_hash
    assert payload["policy"]["revisionLineage"] == (
        "prior_snapshot_hash_is_explicit_but_existence_not_verified_without_persistence"
    )
    assert payload["policy"]["persistentAppendOnlyStorage"] is False


def test_investment_journal_api_happy_path() -> None:
    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/investment-journal/snapshot",
        json=_api_payload(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "snapshot_ready"
    assert data["symbol"] == "AAPL"
    assert len(data["snapshotHash"]) == 64
    assert data["advisoryStatus"] == "no_advice"
    assert data["productionEligible"] is False
    assert data["isWeightingReady"] is False
    assert data["policy"]["automaticTrading"] is False
    assert data["policy"]["persistentAppendOnlyStorage"] is False


@pytest.mark.parametrize("target", ["recordedAt", "asOf", "referenceAvailableAt"])
def test_investment_journal_api_rejects_naive_times_with_400(target: str) -> None:
    payload = _api_payload()
    if target == "referenceAvailableAt":
        payload["references"][0]["availableAt"] = "2026-01-09T11:00:00"
    else:
        payload[target] = "2026-01-09T12:00:00"

    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/investment-journal/snapshot",
        json=payload,
    )

    assert response.status_code == 400
    assert "zona horaria" in response.json()["detail"]


class _MaliciousSnapshot:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def to_api_dict(self) -> dict[str, object]:
        return self._payload


def test_investment_journal_api_fails_closed_on_false_persistence_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    valid = _freeze().to_api_dict()
    valid["policy"] = dict(valid["policy"])
    valid["policy"]["persistentAppendOnlyStorage"] = True
    monkeypatch.setattr(
        journal_api.investment_journal_service,
        "freeze_snapshot",
        lambda **_: _MaliciousSnapshot(valid),
    )

    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/investment-journal/snapshot",
        json=_api_payload(),
    )

    assert response.status_code == 500
    assert "append-only" in response.json()["detail"]


def test_investment_journal_api_fails_closed_on_advice(monkeypatch: pytest.MonkeyPatch) -> None:
    valid = _freeze().to_api_dict()
    valid["advisoryStatus"] = "advice"
    monkeypatch.setattr(
        journal_api.investment_journal_service,
        "freeze_snapshot",
        lambda **_: _MaliciousSnapshot(valid),
    )

    response = TestClient(app).post(
        "/api/v1/recommendations/professional-research/investment-journal/snapshot",
        json=_api_payload(),
    )

    assert response.status_code == 500
    assert "no-advice" in response.json()["detail"]
