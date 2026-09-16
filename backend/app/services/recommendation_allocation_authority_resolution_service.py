from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_correlation_evidence_repository import (
    RecommendationPortfolioCorrelationEvidenceRepository,
)
from app.repositories.recommendation_uncertainty_bound_action_candidate_repository import (
    RecommendationUncertaintyBoundActionCandidateRepository,
)


class _ActionRepository(Protocol):
    def get(self, *, candidate_fingerprint: str) -> dict[str, Any] | None: ...


class _CorrelationRepository(Protocol):
    def get(self, *, evidence_fingerprint: str) -> dict[str, Any] | None: ...


class RecommendationAllocationAuthorityIndex:
    """Read-only index over persisted allocation authorities.

    It does not select a preferred model/provider. It only exposes exact PIT matches;
    the resolution service rejects missing or ambiguous matches.
    """

    def __init__(self, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()

    def action_fingerprints(
        self,
        *,
        instrument_id: int,
        as_of: datetime,
    ) -> tuple[str, ...]:
        self._database.initialize()
        RecommendationUncertaintyBoundActionCandidateRepository(self._database).initialize()
        cutoff = self._aware_utc(as_of).isoformat()
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT candidate_fingerprint
                FROM athena_recommendation_uncertainty_bound_actions
                WHERE instrument_id = ? AND as_of = ?
                ORDER BY candidate_fingerprint
                """,
                (instrument_id, cutoff),
            ).fetchall()
        return tuple(str(row["candidate_fingerprint"]) for row in rows)

    def correlation_fingerprints(
        self,
        *,
        left_instrument_id: int,
        right_instrument_id: int,
        as_of: datetime,
    ) -> tuple[str, ...]:
        self._database.initialize()
        RecommendationPortfolioCorrelationEvidenceRepository(self._database).initialize()
        cutoff = self._aware_utc(as_of).isoformat()
        lo = min(left_instrument_id, right_instrument_id)
        hi = max(left_instrument_id, right_instrument_id)
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_fingerprint
                FROM athena_recommendation_portfolio_correlation_evidence
                WHERE knowledge_cutoff = ?
                  AND (
                    (left_instrument_id = ? AND right_instrument_id = ?)
                    OR
                    (left_instrument_id = ? AND right_instrument_id = ?)
                  )
                ORDER BY evidence_fingerprint
                """,
                (cutoff, lo, hi, hi, lo),
            ).fetchall()
        return tuple(str(row["evidence_fingerprint"]) for row in rows)

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)


class RecommendationAllocationAuthorityResolutionService:
    """Resolve exact persisted authorities without inventing defaults.

    Allocation policy and economic contract remain explicit product/policy inputs.
    Internal action/correlation fingerprints are resolved server-side. A missing or
    ambiguous authority is a hard not-ready condition.
    """

    ARTIFACT_VERSION = "athena-allocation-authority-resolution-v1"

    def __init__(
        self,
        *,
        index: RecommendationAllocationAuthorityIndex | None = None,
        action_repository: _ActionRepository | None = None,
        correlation_repository: _CorrelationRepository | None = None,
    ) -> None:
        self._index = index if index is not None else RecommendationAllocationAuthorityIndex()
        self._action_repository = (
            action_repository
            if action_repository is not None
            else RecommendationUncertaintyBoundActionCandidateRepository()
        )
        self._correlation_repository = (
            correlation_repository
            if correlation_repository is not None
            else RecommendationPortfolioCorrelationEvidenceRepository()
        )

    def resolve(
        self,
        *,
        instrument_id: int,
        horizon_days: int,
        held_instrument_ids: list[int] | tuple[int, ...],
        as_of: datetime,
    ) -> dict[str, Any]:
        instrument_id = self._positive_int(instrument_id, "instrument_id")
        horizon_days = self._positive_int(horizon_days, "horizon_days")
        cutoff = self._aware_utc(as_of)

        held: list[int] = []
        seen = set()
        for raw in held_instrument_ids:
            item = self._positive_int(raw, "held_instrument_id")
            if item in seen:
                raise ValueError("held_instrument_ids no puede contener duplicados.")
            seen.add(item)
            held.append(item)

        action_matches: list[tuple[str, dict[str, Any]]] = []
        for fingerprint in self._index.action_fingerprints(
            instrument_id=instrument_id,
            as_of=cutoff,
        ):
            record = self._action_repository.get(candidate_fingerprint=fingerprint)
            if record is None:
                raise RuntimeError("El índice referencia una autoridad de acción inexistente.")
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise RuntimeError("La autoridad de acción persistida es inválida.")
            if int(artifact.get("instrumentId") or 0) != instrument_id:
                raise RuntimeError("La autoridad de acción cambió instrumentId.")
            if int(artifact.get("horizonDays") or 0) != horizon_days:
                continue
            if self._parse_aware(artifact.get("asOf")) != cutoff:
                raise RuntimeError("La autoridad de acción cambió el corte PIT.")
            if artifact.get("advisoryStatus") != "no_advice":
                raise RuntimeError("La autoridad de acción intentó emitir advice.")
            for field in (
                "recommendationCandidateReady",
                "productionEligible",
                "allocationEligible",
                "automaticTrading",
            ):
                if artifact.get(field) is not False:
                    raise RuntimeError(f"La autoridad de acción violó {field}=False.")
            action_matches.append((fingerprint, record))

        if len(action_matches) != 1:
            status = "missing" if not action_matches else "ambiguous"
            return self._not_ready(
                instrument_id=instrument_id,
                horizon_days=horizon_days,
                as_of=cutoff,
                reason=f"action_authority_{status}",
            )

        correlation_fingerprints: list[str] = []
        for held_id in held:
            if held_id == instrument_id:
                continue
            matches = self._index.correlation_fingerprints(
                left_instrument_id=instrument_id,
                right_instrument_id=held_id,
                as_of=cutoff,
            )
            if len(matches) != 1:
                status = "missing" if not matches else "ambiguous"
                return self._not_ready(
                    instrument_id=instrument_id,
                    horizon_days=horizon_days,
                    as_of=cutoff,
                    reason=f"correlation_authority_{status}:{held_id}",
                )
            fingerprint = matches[0]
            record = self._correlation_repository.get(evidence_fingerprint=fingerprint)
            if record is None:
                raise RuntimeError("El índice referencia una correlación inexistente.")
            artifact = record.get("artifact")
            if not isinstance(artifact, dict):
                raise RuntimeError("La correlación persistida es inválida.")
            pair = {
                int(artifact.get("leftInstrumentId") or 0),
                int(artifact.get("rightInstrumentId") or 0),
            }
            if pair != {instrument_id, held_id}:
                raise RuntimeError("La correlación cambió el par canónico.")
            if self._parse_aware(artifact.get("knowledgeCutoff")) != cutoff:
                raise RuntimeError("La correlación cambió el corte PIT.")
            if artifact.get("advisoryStatus") != "no_advice":
                raise RuntimeError("La correlación intentó emitir advice.")
            if artifact.get("productionEligible") is not False or artifact.get(
                "allocationEligible"
            ) is not False or artifact.get("automaticTrading") is not False:
                raise RuntimeError("La correlación intentó escapar del contrato fail-closed.")
            correlation_fingerprints.append(fingerprint)

        action_fingerprint, action_record = action_matches[0]
        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "status": "allocation_authorities_resolved_non_advisory",
            "asOf": cutoff.isoformat(),
            "instrumentId": instrument_id,
            "horizonDays": horizon_days,
            "uncertaintyBoundActionCandidateFingerprint": action_fingerprint,
            "actionAuthorityRecordFingerprint": action_record.get("record_fingerprint"),
            "correlationEvidenceFingerprints": correlation_fingerprints,
            "allocationAuthoritiesReady": True,
            "callerSuppliedInternalFingerprintsRequired": False,
            "policySelectionPerformed": False,
            "economicContractInvented": False,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

    def _not_ready(
        self,
        *,
        instrument_id: int,
        horizon_days: int,
        as_of: datetime,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "artifactVersion": self.ARTIFACT_VERSION,
            "status": "allocation_authorities_not_ready",
            "asOf": as_of.isoformat(),
            "instrumentId": instrument_id,
            "horizonDays": horizon_days,
            "allocationAuthoritiesReady": False,
            "reason": reason,
            "callerSuppliedInternalFingerprintsRequired": False,
            "policySelectionPerformed": False,
            "economicContractInvented": False,
            "advisoryStatus": "no_advice",
            "recommendationCandidateReady": False,
            "productionEligible": False,
            "allocationEligible": False,
            "automaticTrading": False,
        }

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field} debe ser entero positivo.")
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field} debe ser entero positivo.") from exc
        if result <= 0:
            raise ValueError(f"{field} debe ser entero positivo.")
        return result

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of debe incluir zona horaria.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_aware(value: object) -> datetime:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("La autoridad contiene timestamp inválido.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RuntimeError("La autoridad contiene timestamp sin zona horaria.")
        return parsed.astimezone(timezone.utc)
