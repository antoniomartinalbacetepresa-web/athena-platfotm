from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.production_recovery_readiness_service import (
    ProductionRecoveryReadinessReport,
    ProductionRecoveryReadinessService,
    RecoveryEvidence,
)


@dataclass(frozen=True)
class OperationalRecoveryEvidence:
    evidence: RecoveryEvidence
    environment: str
    source: str
    observed_at: datetime
    independently_verified: bool = False


class OperationalRecoveryEvidenceService:
    """Require attributable production evidence without promoting operator assertions."""

    def __init__(self, *, max_observation_age: timedelta = timedelta(hours=24)) -> None:
        if max_observation_age <= timedelta(0):
            raise ValueError("max_observation_age debe ser positivo.")
        self._max_observation_age = max_observation_age
        self._readiness = ProductionRecoveryReadinessService()

    def evaluate(
        self,
        operational: OperationalRecoveryEvidence,
        *,
        now: datetime | None = None,
    ) -> ProductionRecoveryReadinessReport:
        evaluated_at = self._aware_utc(now or datetime.now(timezone.utc), "now")
        observed_at = self._aware_utc(operational.observed_at, "observed_at")
        base = self._readiness.evaluate(operational.evidence, now=evaluated_at)
        checks = {
            "productionEnvironmentScoped": operational.environment.strip().lower() == "production",
            "operationalEvidenceSourceIdentified": bool(operational.source.strip()),
            "operationalEvidenceRecent": timedelta(0) <= evaluated_at - observed_at <= self._max_observation_age,
            "operationalEvidenceIndependentlyVerified": operational.independently_verified is True,
            **base.checks,
        }
        messages = {
            "productionEnvironmentScoped": "La evidencia no está vinculada explícitamente al entorno production.",
            "operationalEvidenceSourceIdentified": "La evidencia operacional no identifica su fuente.",
            "operationalEvidenceRecent": "La observación operacional es futura o demasiado antigua.",
            "operationalEvidenceIndependentlyVerified": (
                "La evidencia operacional no tiene verificación independiente; una declaración del operador no basta."
            ),
        }
        blockers = tuple(messages[name] for name in messages if not checks[name]) + base.blockers
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
