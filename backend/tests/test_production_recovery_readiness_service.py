from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import inf, nan

import pytest

from app.services.production_recovery_readiness_service import (
    ProductionRecoveryReadinessService,
    RecoveryEvidence,
)


def _now() -> datetime:
    return datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)


def _complete_evidence() -> RecoveryEvidence:
    now = _now()
    return RecoveryEvidence(
        last_backup_at=now - timedelta(hours=1),
        last_restore_drill_at=now - timedelta(days=2),
        scheduled_backup_enabled=True,
        offsite_copy_verified=True,
        rpo_hours_measured=6.0,
        rto_hours_measured=1.5,
    )


def test_complete_operational_evidence_passes_without_authorizing_production() -> None:
    report = ProductionRecoveryReadinessService().evaluate(
        _complete_evidence(),
        now=_now(),
    )

    assert report.ready is True
    assert report.blockers == ()
    payload = report.to_dict()
    assert payload["status"] == "diagnostic_only"
    assert payload["productionAuthorization"] is False
    assert all(payload["checks"].values())


def test_missing_external_operational_evidence_fails_closed() -> None:
    report = ProductionRecoveryReadinessService().evaluate(
        RecoveryEvidence(
            last_backup_at=None,
            last_restore_drill_at=None,
            scheduled_backup_enabled=False,
            offsite_copy_verified=False,
            rpo_hours_measured=None,
            rto_hours_measured=None,
        ),
        now=_now(),
    )

    assert report.ready is False
    assert len(report.blockers) == 6
    assert report.checks == {
        "scheduledBackupEnabled": False,
        "offsiteCopyVerified": False,
        "recentBackupVerified": False,
        "recentRestoreDrillVerified": False,
        "rpoMeasuredWithinTarget": False,
        "rtoMeasuredWithinTarget": False,
    }


def test_stale_backup_and_restore_drill_do_not_pass() -> None:
    now = _now()
    report = ProductionRecoveryReadinessService().evaluate(
        RecoveryEvidence(
            last_backup_at=now - timedelta(hours=25),
            last_restore_drill_at=now - timedelta(days=31),
            scheduled_backup_enabled=True,
            offsite_copy_verified=True,
            rpo_hours_measured=4.0,
            rto_hours_measured=2.0,
        ),
        now=now,
    )

    assert report.ready is False
    assert report.checks["recentBackupVerified"] is False
    assert report.checks["recentRestoreDrillVerified"] is False


def test_future_dated_evidence_is_rejected_as_not_recent() -> None:
    now = _now()
    report = ProductionRecoveryReadinessService().evaluate(
        RecoveryEvidence(
            last_backup_at=now + timedelta(minutes=1),
            last_restore_drill_at=now + timedelta(minutes=1),
            scheduled_backup_enabled=True,
            offsite_copy_verified=True,
            rpo_hours_measured=1.0,
            rto_hours_measured=1.0,
        ),
        now=now,
    )

    assert report.ready is False
    assert report.checks["recentBackupVerified"] is False
    assert report.checks["recentRestoreDrillVerified"] is False


@pytest.mark.parametrize("bad", [0.0, -1.0, inf, nan])
def test_invalid_thresholds_fail_closed(bad: float) -> None:
    with pytest.raises(ValueError):
        ProductionRecoveryReadinessService(max_rpo_hours=bad)
    with pytest.raises(ValueError):
        ProductionRecoveryReadinessService(max_rto_hours=bad)


@pytest.mark.parametrize("field", ["rpo", "rto"])
@pytest.mark.parametrize("bad", [0.0, -1.0, inf, nan])
def test_invalid_measured_recovery_values_fail_closed(field: str, bad: float) -> None:
    evidence = _complete_evidence()
    kwargs = {
        "last_backup_at": evidence.last_backup_at,
        "last_restore_drill_at": evidence.last_restore_drill_at,
        "scheduled_backup_enabled": evidence.scheduled_backup_enabled,
        "offsite_copy_verified": evidence.offsite_copy_verified,
        "rpo_hours_measured": bad if field == "rpo" else evidence.rpo_hours_measured,
        "rto_hours_measured": bad if field == "rto" else evidence.rto_hours_measured,
    }

    with pytest.raises(ValueError):
        ProductionRecoveryReadinessService().evaluate(
            RecoveryEvidence(**kwargs),
            now=_now(),
        )


def test_naive_timestamps_are_rejected() -> None:
    evidence = _complete_evidence()
    with pytest.raises(ValueError):
        ProductionRecoveryReadinessService().evaluate(
            RecoveryEvidence(
                last_backup_at=datetime(2026, 9, 11, 12, 0),
                last_restore_drill_at=evidence.last_restore_drill_at,
                scheduled_backup_enabled=True,
                offsite_copy_verified=True,
                rpo_hours_measured=1.0,
                rto_hours_measured=1.0,
            ),
            now=_now(),
        )
