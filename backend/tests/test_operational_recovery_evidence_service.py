from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.operational_recovery_evidence_service import (
    OperationalRecoveryEvidence,
    OperationalRecoveryEvidenceService,
)
from app.services.production_recovery_readiness_service import RecoveryEvidence


def _now() -> datetime:
    return datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)


def _recovery(now: datetime) -> RecoveryEvidence:
    return RecoveryEvidence(
        last_backup_at=now - timedelta(hours=1),
        last_restore_drill_at=now - timedelta(days=1),
        scheduled_backup_enabled=True,
        offsite_copy_verified=True,
        rpo_hours_measured=2.0,
        rto_hours_measured=1.0,
    )


def test_production_scoped_attributable_recent_evidence_still_requires_independent_verification() -> None:
    now = _now()
    report = OperationalRecoveryEvidenceService().evaluate(
        OperationalRecoveryEvidence(
            evidence=_recovery(now),
            environment="production",
            source="deployment-recovery-controller",
            observed_at=now - timedelta(minutes=5),
        ),
        now=now,
    )
    assert report.ready is False
    assert report.checks["operationalEvidenceIndependentlyVerified"] is False
    assert report.to_dict()["productionAuthorization"] is False


def test_independently_verified_production_evidence_can_pass_diagnostic_without_authorizing_production() -> None:
    now = _now()
    report = OperationalRecoveryEvidenceService().evaluate(
        OperationalRecoveryEvidence(
            evidence=_recovery(now),
            environment="production",
            source="external-recovery-verifier",
            observed_at=now - timedelta(minutes=5),
            independently_verified=True,
        ),
        now=now,
    )
    assert report.ready is True
    assert all(report.checks.values())
    assert report.to_dict()["productionAuthorization"] is False


def test_fixture_like_unscoped_evidence_cannot_claim_production_readiness() -> None:
    now = _now()
    report = OperationalRecoveryEvidenceService().evaluate(
        OperationalRecoveryEvidence(
            evidence=_recovery(now),
            environment="test",
            source="pytest-fixture",
            observed_at=now,
            independently_verified=True,
        ),
        now=now,
    )
    assert report.ready is False
    assert report.checks["productionEnvironmentScoped"] is False


def test_missing_source_or_stale_observation_fails_closed() -> None:
    now = _now()
    report = OperationalRecoveryEvidenceService().evaluate(
        OperationalRecoveryEvidence(
            evidence=_recovery(now),
            environment="production",
            source="   ",
            observed_at=now - timedelta(hours=25),
            independently_verified=True,
        ),
        now=now,
    )
    assert report.ready is False
    assert report.checks["operationalEvidenceSourceIdentified"] is False
    assert report.checks["operationalEvidenceRecent"] is False


def test_future_observation_fails_closed() -> None:
    now = _now()
    report = OperationalRecoveryEvidenceService().evaluate(
        OperationalRecoveryEvidence(
            evidence=_recovery(now),
            environment="production",
            source="external-recovery-verifier",
            observed_at=now + timedelta(seconds=1),
            independently_verified=True,
        ),
        now=now,
    )
    assert report.ready is False
    assert report.checks["operationalEvidenceRecent"] is False
