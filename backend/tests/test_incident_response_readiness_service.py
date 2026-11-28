from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.incident_response_readiness_service import (
    IncidentResponseEvidence,
    IncidentResponseReadinessService,
)


def _now() -> datetime:
    return datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc)


def _complete() -> IncidentResponseEvidence:
    now = _now()
    return IncidentResponseEvidence(
        runbook_reviewed_at=now - timedelta(days=10),
        exercise_completed_at=now - timedelta(days=30),
        incident_owner_assigned=True,
        escalation_channel_verified=True,
        credential_revocation_procedure_verified=True,
        recovery_procedure_verified=True,
    )


def test_complete_evidence_passes_without_authorizing_production() -> None:
    report = IncidentResponseReadinessService().evaluate(_complete(), now=_now())
    assert report.ready is True
    assert report.blockers == ()
    assert all(report.checks.values())
    assert report.to_dict()["productionAuthorization"] is False
    assert report.to_dict()["automaticTrading"] is False


def test_missing_operational_evidence_fails_closed() -> None:
    report = IncidentResponseReadinessService().evaluate(
        IncidentResponseEvidence(None, None, False, False, False, False),
        now=_now(),
    )
    assert report.ready is False
    assert len(report.blockers) == 6
    assert not any(report.checks.values())


def test_stale_or_future_evidence_never_counts_as_recent() -> None:
    now = _now()
    service = IncidentResponseReadinessService()
    stale = IncidentResponseEvidence(
        now - timedelta(days=91), now - timedelta(days=181), True, True, True, True
    )
    future = IncidentResponseEvidence(
        now + timedelta(minutes=1), now + timedelta(minutes=1), True, True, True, True
    )
    assert service.evaluate(stale, now=now).ready is False
    assert service.evaluate(future, now=now).ready is False


def test_naive_timestamps_and_invalid_windows_are_rejected() -> None:
    with pytest.raises(ValueError):
        IncidentResponseReadinessService(max_exercise_age=timedelta(0))
    evidence = _complete()
    with pytest.raises(ValueError, match="zona horaria"):
        IncidentResponseReadinessService().evaluate(
            IncidentResponseEvidence(
                datetime(2026, 9, 21, 18, 0),
                evidence.exercise_completed_at,
                True, True, True, True,
            ),
            now=_now(),
        )
