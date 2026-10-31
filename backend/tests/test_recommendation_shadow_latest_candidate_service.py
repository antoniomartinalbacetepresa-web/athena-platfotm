from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from app.services.recommendation_shadow_latest_candidate_service import (
    RecommendationShadowLatestCandidateService,
)


FP1 = "1" * 64
FP2 = "2" * 64
CONF = "a" * 64


class FakeRepository:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records

    def list_all(self) -> list[dict[str, Any]]:
        return self.records


class FakeCandidateService:
    def validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if artifact.get("tampered") is True:
            raise ValueError("tampered")
        return artifact


def _record(
    *,
    record_id: int,
    fingerprint: str,
    candidate_as_of: str,
    persisted_at: str,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "candidate_fingerprint": fingerprint,
        "confirmation_fingerprint": CONF,
        "artifact_version": "shadow-live-candidate-v1",
        "created_at": persisted_at,
        "artifact": {
            "artifactVersion": "shadow-live-candidate-v1",
            "candidateFingerprint": fingerprint,
            "confirmationEvidenceFingerprint": CONF,
            "symbol": "AAPL",
            "asOf": candidate_as_of,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "action": None,
            "score": None,
            "conviction": None,
        },
    }


def _service(records: list[dict[str, Any]]) -> RecommendationShadowLatestCandidateService:
    return RecommendationShadowLatestCandidateService(
        repository=FakeRepository(records),
        candidate_service=FakeCandidateService(),
    )


def test_resolve_returns_latest_candidate_known_at_cutoff() -> None:
    older = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T10:00:00+00:00",
        persisted_at="2026-09-01T10:05:00+00:00",
    )
    newer = _record(
        record_id=2,
        fingerprint=FP2,
        candidate_as_of="2026-09-01T11:00:00+00:00",
        persisted_at="2026-09-01T11:05:00+00:00",
    )

    result = _service([older, newer]).resolve(
        as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    )

    assert result["status"] == "shadow_candidate_available_non_advisory"
    assert result["recordId"] == 2
    assert result["candidate"] is newer["artifact"]
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_resolve_blocks_candidate_persisted_after_historical_cutoff() -> None:
    leaked = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T10:00:00+00:00",
        persisted_at="2026-09-01T13:00:00+00:00",
    )

    result = _service([leaked]).resolve(
        as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    )

    assert result["status"] == "no_shadow_candidate_known_at_cutoff"
    assert result["candidate"] is None


def test_resolve_fails_closed_when_record_fingerprint_is_substituted() -> None:
    record = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T10:00:00+00:00",
        persisted_at="2026-09-01T10:05:00+00:00",
    )
    record["candidate_fingerprint"] = FP2

    with pytest.raises(ValueError, match="fingerprint persistido"):
        _service([record]).resolve(
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        )


def test_resolve_fails_closed_on_tampered_persisted_artifact() -> None:
    record = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T10:00:00+00:00",
        persisted_at="2026-09-01T10:05:00+00:00",
    )
    record["artifact"]["tampered"] = True

    with pytest.raises(ValueError, match="tampered"):
        _service([record]).resolve(
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        )


def test_resolve_fails_closed_if_candidate_claims_as_of_after_persistence() -> None:
    record = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T11:00:00+00:00",
        persisted_at="2026-09-01T10:05:00+00:00",
    )

    with pytest.raises(ValueError, match="persistido antes"):
        _service([record]).resolve(
            as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
        )


def test_resolve_rejects_naive_cutoff() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        _service([]).resolve(as_of=datetime(2026, 9, 1, 12))


def test_resolve_does_not_mutate_repository_artifact() -> None:
    record = _record(
        record_id=1,
        fingerprint=FP1,
        candidate_as_of="2026-09-01T10:00:00+00:00",
        persisted_at="2026-09-01T10:05:00+00:00",
    )
    before = deepcopy(record)

    _service([record]).resolve(as_of=datetime(2026, 9, 1, 12, tzinfo=timezone.utc))

    assert record == before
