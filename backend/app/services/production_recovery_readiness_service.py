from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class RecoveryEvidence:
    last_backup_at: datetime | None
    last_restore_drill_at: datetime | None
    scheduled_backup_enabled: bool
    offsite_copy_verified: bool
    rpo_hours_measured: float | None
    rto_hours_measured: float | None


@dataclass(frozen=True)
class ProductionRecoveryReadinessReport:
    ready: bool
    checks: dict[str, bool]
    blockers: tuple[str, ...]
    evaluated_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": dict(self.checks),
            "blockers": list(self.blockers),
            "evaluatedAtUtc": self.evaluated_at_utc,
            "status": "diagnostic_only",
            "productionAuthorization": False,
        }


class ProductionRecoveryReadinessService:
    """Evaluates operator-supplied recovery evidence without fabricating it.

    This service intentionally does not inspect CI fixtures or local backup files and
    infer that production recovery exists. It only evaluates explicit operational
    evidence supplied by deployment tooling or an operator.
    """

    def __init__(
        self,
        *,
        max_backup_age: timedelta = timedelta(hours=24),
        max_restore_drill_age: timedelta = timedelta(days=30),
        max_rpo_hours: float = 24.0,
        max_rto_hours: float = 4.0,
    ) -> None:
        if max_backup_age <= timedelta(0):
            raise ValueError("max_backup_age debe ser positivo.")
        if max_restore_drill_age <= timedelta(0):
            raise ValueError("max_restore_drill_age debe ser positivo.")
        self._max_rpo_hours = self._positive_finite(max_rpo_hours, "max_rpo_hours")
        self._max_rto_hours = self._positive_finite(max_rto_hours, "max_rto_hours")
        self._max_backup_age = max_backup_age
        self._max_restore_drill_age = max_restore_drill_age

    def evaluate(
        self,
        evidence: RecoveryEvidence,
        *,
        now: datetime | None = None,
    ) -> ProductionRecoveryReadinessReport:
        evaluated_at = self._aware_utc(now or datetime.now(timezone.utc), "now")

        backup_at = self._optional_aware_utc(evidence.last_backup_at, "last_backup_at")
        restore_at = self._optional_aware_utc(
            evidence.last_restore_drill_at,
            "last_restore_drill_at",
        )
        rpo = self._optional_positive_finite(evidence.rpo_hours_measured, "rpo_hours_measured")
        rto = self._optional_positive_finite(evidence.rto_hours_measured, "rto_hours_measured")

        backup_recent = (
            backup_at is not None
            and timedelta(0) <= evaluated_at - backup_at <= self._max_backup_age
        )
        restore_recent = (
            restore_at is not None
            and timedelta(0) <= evaluated_at - restore_at <= self._max_restore_drill_age
        )

        checks = {
            "scheduledBackupEnabled": evidence.scheduled_backup_enabled is True,
            "offsiteCopyVerified": evidence.offsite_copy_verified is True,
            "recentBackupVerified": backup_recent,
            "recentRestoreDrillVerified": restore_recent,
            "rpoMeasuredWithinTarget": rpo is not None and rpo <= self._max_rpo_hours,
            "rtoMeasuredWithinTarget": rto is not None and rto <= self._max_rto_hours,
        }

        blocker_messages = {
            "scheduledBackupEnabled": "No hay evidencia de backup programado activo.",
            "offsiteCopyVerified": "No hay evidencia de copia off-site verificada.",
            "recentBackupVerified": "No hay un backup verificado dentro de la ventana exigida.",
            "recentRestoreDrillVerified": "No hay un restore drill reciente dentro de la ventana exigida.",
            "rpoMeasuredWithinTarget": "El RPO real no está medido o supera el objetivo.",
            "rtoMeasuredWithinTarget": "El RTO real no está medido o supera el objetivo.",
        }
        blockers = tuple(
            blocker_messages[name]
            for name, passed in checks.items()
            if not passed
        )

        return ProductionRecoveryReadinessReport(
            ready=all(checks.values()),
            checks=checks,
            blockers=blockers,
            evaluated_at_utc=evaluated_at.isoformat(),
        )

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _optional_aware_utc(cls, value: datetime | None, field: str) -> datetime | None:
        if value is None:
            return None
        return cls._aware_utc(value, field)

    @staticmethod
    def _positive_finite(value: float, field: str) -> float:
        numeric = float(value)
        if not isfinite(numeric) or numeric <= 0:
            raise ValueError(f"{field} debe ser finito y positivo.")
        return numeric

    @classmethod
    def _optional_positive_finite(cls, value: float | None, field: str) -> float | None:
        if value is None:
            return None
        return cls._positive_finite(value, field)
