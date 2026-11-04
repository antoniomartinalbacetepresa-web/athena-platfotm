from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class IncidentResponseEvidence:
    runbook_reviewed_at: datetime | None
    exercise_completed_at: datetime | None
    incident_owner_assigned: bool
    escalation_channel_verified: bool
    credential_revocation_procedure_verified: bool
    recovery_procedure_verified: bool


@dataclass(frozen=True)
class IncidentResponseReadinessReport:
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
            "automaticTrading": False,
        }


class IncidentResponseReadinessService:
    """Evaluate explicit operator evidence without manufacturing production proof."""

    def __init__(
        self,
        *,
        max_runbook_review_age: timedelta = timedelta(days=90),
        max_exercise_age: timedelta = timedelta(days=180),
    ) -> None:
        if max_runbook_review_age <= timedelta(0) or max_exercise_age <= timedelta(0):
            raise ValueError("Las ventanas de evidencia deben ser positivas.")
        self._max_runbook_review_age = max_runbook_review_age
        self._max_exercise_age = max_exercise_age

    def evaluate(
        self,
        evidence: IncidentResponseEvidence,
        *,
        now: datetime | None = None,
    ) -> IncidentResponseReadinessReport:
        evaluated_at = self._aware_utc(now or datetime.now(timezone.utc), "now")
        runbook_at = self._optional_aware_utc(evidence.runbook_reviewed_at, "runbook_reviewed_at")
        exercise_at = self._optional_aware_utc(evidence.exercise_completed_at, "exercise_completed_at")

        checks = {
            "recentRunbookReviewVerified": self._recent(runbook_at, evaluated_at, self._max_runbook_review_age),
            "recentExerciseVerified": self._recent(exercise_at, evaluated_at, self._max_exercise_age),
            "incidentOwnerAssigned": evidence.incident_owner_assigned is True,
            "escalationChannelVerified": evidence.escalation_channel_verified is True,
            "credentialRevocationProcedureVerified": evidence.credential_revocation_procedure_verified is True,
            "recoveryProcedureVerified": evidence.recovery_procedure_verified is True,
        }
        messages = {
            "recentRunbookReviewVerified": "No hay revisión reciente verificada del runbook de incidentes.",
            "recentExerciseVerified": "No hay simulacro reciente verificado de respuesta a incidentes.",
            "incidentOwnerAssigned": "No hay responsable operativo de incidentes confirmado.",
            "escalationChannelVerified": "No hay canal de escalado operativo verificado.",
            "credentialRevocationProcedureVerified": "No se ha verificado el procedimiento de revocación de credenciales.",
            "recoveryProcedureVerified": "No se ha verificado el procedimiento de recuperación operacional.",
        }
        blockers = tuple(messages[name] for name, passed in checks.items() if not passed)
        return IncidentResponseReadinessReport(
            ready=all(checks.values()),
            checks=checks,
            blockers=blockers,
            evaluated_at_utc=evaluated_at.isoformat(),
        )

    @staticmethod
    def _recent(value: datetime | None, now: datetime, maximum_age: timedelta) -> bool:
        return value is not None and timedelta(0) <= now - value <= maximum_age

    @staticmethod
    def _aware_utc(value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @classmethod
    def _optional_aware_utc(cls, value: datetime | None, field: str) -> datetime | None:
        return None if value is None else cls._aware_utc(value, field)
