from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Callable

from app.database.athena_database import AthenaDatabase
from app.services.canonical_market_cap_service import CanonicalMarketCapService


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CanonicalWeightingProposal:
    proposal_id: int
    status: str
    created_at: str
    created_by: str
    approved_at: str | None
    approved_by: str | None
    approval_note: str | None
    region_weights: dict[str, float]
    evidence_snapshot: dict[str, Any]
    evidence_sha256: str

    @property
    def human_approved(self) -> bool:
        return self.status == "approved" and bool(self.approved_by) and bool(self.approved_at)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "proposalId": self.proposal_id,
            "status": self.status,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "approvedAt": self.approved_at,
            "approvedBy": self.approved_by,
            "approvalNote": self.approval_note,
            "regionWeights": dict(self.region_weights),
            "evidenceSha256": self.evidence_sha256,
            "humanApproved": self.human_approved,
            "automaticApproval": False,
            "automaticTrading": False,
        }


class CanonicalWeightingGovernanceService:
    """Fail-closed governance boundary for canonical regional market weights.

    The quantitative engine may create immutable proposals, but only an explicit
    human approval call can make one eligible for consumption. Creating, reading,
    or refreshing diagnostics never approves a proposal. An approval remains
    consumable only while it is the latest governance record and the current
    canonical evidence fingerprint exactly matches the evidence the human reviewed.
    """

    _REGIONS = ("america", "europe", "asia")

    def __init__(self, *, database: AthenaDatabase | None = None, clock: Clock | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)
        self._initialize_schema()

    def create_proposal(self, *, created_by: str) -> CanonicalWeightingProposal:
        actor = self._required_text(created_by, "created_by")
        snapshot, region_weights = self._current_evidence_snapshot()
        snapshot_json = self._canonical_json(snapshot)
        evidence_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        created_at = self._aware_utc(self._clock(), "clock").isoformat()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO canonical_weighting_proposals (
                    status, created_at, created_by, region_weights_json,
                    evidence_snapshot_json, evidence_sha256
                ) VALUES ('pending_human_approval', ?, ?, ?, ?, ?)""",
                (created_at, actor, self._canonical_json(region_weights), snapshot_json, evidence_hash),
            )
            proposal_id = int(cursor.lastrowid)
        return self.get_proposal(proposal_id)

    def approve_proposal(self, proposal_id: int, *, approved_by: str, approval_note: str) -> CanonicalWeightingProposal:
        if proposal_id <= 0:
            raise ValueError("proposal_id debe ser positivo.")
        approver = self._required_text(approved_by, "approved_by")
        note = self._required_text(approval_note, "approval_note")
        proposal = self.get_proposal(proposal_id)
        if proposal.status != "pending_human_approval":
            raise ValueError("Solo una propuesta pendiente puede recibir aprobación humana.")
        if approver.casefold() == proposal.created_by.casefold():
            raise ValueError("La aprobación humana requiere separación de funciones: proponente y aprobador deben ser distintos.")
        self._verify_integrity(proposal)
        current_hash = self._current_evidence_hash()
        if current_hash != proposal.evidence_sha256:
            raise ValueError("La evidencia canónica cambió desde la propuesta; debe generarse y revisarse una nueva propuesta.")
        approved_at = self._aware_utc(self._clock(), "clock").isoformat()
        with self._database.connect() as connection:
            latest = connection.execute(
                "SELECT id FROM canonical_weighting_proposals ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest is None or int(latest["id"]) != proposal_id:
                raise ValueError("La propuesta fue sustituida por una revisión posterior; solo la propuesta más reciente puede aprobarse.")
            cursor = connection.execute(
                """UPDATE canonical_weighting_proposals
                SET status = 'approved', approved_at = ?, approved_by = ?, approval_note = ?
                WHERE id = ? AND status = 'pending_human_approval'""",
                (approved_at, approver, note, proposal_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("La propuesta cambió antes de registrar la aprobación.")
        return self.get_proposal(proposal_id)

    def reject_proposal(self, proposal_id: int, *, rejected_by: str, rejection_note: str) -> CanonicalWeightingProposal:
        if proposal_id <= 0:
            raise ValueError("proposal_id debe ser positivo.")
        actor = self._required_text(rejected_by, "rejected_by")
        note = self._required_text(rejection_note, "rejection_note")
        proposal = self.get_proposal(proposal_id)
        if proposal.status != "pending_human_approval":
            raise ValueError("Solo una propuesta pendiente puede rechazarse.")
        if actor.casefold() == proposal.created_by.casefold():
            raise ValueError(
                "El rechazo humano requiere separación de funciones: "
                "proponente y decisor deben ser distintos."
            )
        self._verify_integrity(proposal)
        decided_at = self._aware_utc(self._clock(), "clock").isoformat()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """UPDATE canonical_weighting_proposals
                SET status = 'rejected', approved_at = ?, approved_by = ?, approval_note = ?
                WHERE id = ? AND status = 'pending_human_approval'""",
                (decided_at, actor, note, proposal_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("La propuesta cambió antes de registrar el rechazo.")
        return self.get_proposal(proposal_id)

    def get_approved_weights(self) -> dict[str, Any]:
        # The latest governance record owns the gate. A newer pending or rejected
        # proposal supersedes any older approval and cannot leak its weights.
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM canonical_weighting_proposals ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return self._blocked_response(None, None)
        proposal = self.get_proposal(int(row["id"]))
        if not proposal.human_approved:
            if proposal.status == "rejected":
                return self._blocked_response(
                    proposal.proposal_id,
                    proposal.status,
                    status="blocked_rejected_requires_new_proposal",
                )
            return self._blocked_response(proposal.proposal_id, proposal.status)
        self._verify_integrity(proposal)
        try:
            current_hash = self._current_evidence_hash()
        except ValueError:
            current_hash = None
        if current_hash != proposal.evidence_sha256:
            return {
                "status": "blocked_stale_evidence_requires_human_approval",
                "regionWeights": None,
                "proposalId": proposal.proposal_id,
                "approvedAt": proposal.approved_at,
                "approvedBy": proposal.approved_by,
                "humanApproved": True,
                "evidenceFresh": False,
                "approvalEvidenceSha256": proposal.evidence_sha256,
                "currentEvidenceSha256": current_hash,
                "automaticApproval": False,
                "automaticTrading": False,
            }
        return {
            "status": "human_approved",
            "regionWeights": dict(proposal.region_weights),
            "proposalId": proposal.proposal_id,
            "approvedAt": proposal.approved_at,
            "approvedBy": proposal.approved_by,
            "humanApproved": True,
            "evidenceFresh": True,
            "approvalEvidenceSha256": proposal.evidence_sha256,
            "currentEvidenceSha256": current_hash,
            "automaticApproval": False,
            "automaticTrading": False,
        }

    def _blocked_response(
        self,
        proposal_id: int | None,
        proposal_status: str | None,
        *,
        status: str = "blocked_pending_human_approval",
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "status": status,
            "regionWeights": None,
            "proposalId": proposal_id,
            "humanApproved": False,
            "automaticApproval": False,
            "automaticTrading": False,
        }
        if proposal_status is not None:
            response["proposalStatus"] = proposal_status
        return response

    def get_proposal(self, proposal_id: int) -> CanonicalWeightingProposal:
        if proposal_id <= 0:
            raise ValueError("proposal_id debe ser positivo.")
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM canonical_weighting_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise LookupError("Propuesta de weighting no encontrada.")
        proposal = self._from_row(dict(row))
        self._verify_integrity(proposal)
        return proposal

    def _current_evidence_snapshot(self) -> tuple[dict[str, Any], dict[str, float]]:
        report = CanonicalMarketCapService(database=self._database).get_report()
        self._validate_weights(report.region_weights)
        if report.canonical_market_cap_usd <= 0:
            raise ValueError("No existe capitalización canónica suficiente para proponer pesos.")
        if report.domicile_unresolved_issuer_count > 0:
            raise ValueError("No se puede proponer weighting con emisores canónicos sin domicilio resuelto.")
        if report.median_fallback_market_cap_count > 0:
            raise ValueError("No se puede proponer weighting mientras existan capitalizaciones por fallback de mediana.")
        snapshot = {
            "method": "canonical_identity_complete_listing_market_cap",
            "canonicalIssuerCount": report.canonical_issuer_count,
            "canonicalMarketCapUsd": report.canonical_market_cap_usd,
            "domicileResolvedIssuerCount": report.domicile_resolved_issuer_count,
            "domicileUnresolvedIssuerCount": report.domicile_unresolved_issuer_count,
            "domicileMarketCapCoverage": report.domicile_market_cap_coverage,
            "canonicalListingMarketCapCount": report.canonical_listing_market_cap_count,
            "medianFallbackMarketCapCount": report.median_fallback_market_cap_count,
            "regionMarketCapUsd": dict(report.region_market_cap_usd),
            "regionWeights": dict(report.region_weights),
        }
        return snapshot, dict(report.region_weights)

    def _current_evidence_hash(self) -> str:
        snapshot, _ = self._current_evidence_snapshot()
        return hashlib.sha256(self._canonical_json(snapshot).encode("utf-8")).hexdigest()

    def _initialize_schema(self) -> None:
        self._database.initialize()
        with self._database.connect() as connection:
            connection.executescript(
                """CREATE TABLE IF NOT EXISTS canonical_weighting_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL CHECK (status IN ('pending_human_approval', 'approved', 'rejected')),
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    approved_at TEXT,
                    approved_by TEXT,
                    approval_note TEXT,
                    region_weights_json TEXT NOT NULL,
                    evidence_snapshot_json TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    CHECK (
                        (status = 'pending_human_approval' AND approved_at IS NULL AND approved_by IS NULL AND approval_note IS NULL)
                        OR
                        (status IN ('approved', 'rejected') AND approved_at IS NOT NULL AND approved_by IS NOT NULL AND approval_note IS NOT NULL)
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_canonical_weighting_status_decision
                ON canonical_weighting_proposals(status, approved_at, id);"""
            )

    def _from_row(self, row: dict[str, Any]) -> CanonicalWeightingProposal:
        return CanonicalWeightingProposal(
            proposal_id=int(row["id"]), status=str(row["status"]), created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
            approved_at=None if row["approved_at"] is None else str(row["approved_at"]),
            approved_by=None if row["approved_by"] is None else str(row["approved_by"]),
            approval_note=None if row["approval_note"] is None else str(row["approval_note"]),
            region_weights={str(key): float(value) for key, value in json.loads(str(row["region_weights_json"])).items()},
            evidence_snapshot=json.loads(str(row["evidence_snapshot_json"])),
            evidence_sha256=str(row["evidence_sha256"]),
        )

    def _verify_integrity(self, proposal: CanonicalWeightingProposal) -> None:
        self._validate_weights(proposal.region_weights)
        snapshot_hash = hashlib.sha256(self._canonical_json(proposal.evidence_snapshot).encode("utf-8")).hexdigest()
        if snapshot_hash != proposal.evidence_sha256:
            raise RuntimeError("La evidencia inmutable de la propuesta no supera SHA-256.")
        snapshot_weights = proposal.evidence_snapshot.get("regionWeights")
        if snapshot_weights != proposal.region_weights:
            raise RuntimeError("Los pesos persistidos no coinciden con la evidencia de la propuesta.")

    def _validate_weights(self, weights: dict[str, float]) -> None:
        if set(weights) != set(self._REGIONS):
            raise ValueError("El weighting canónico debe contener america, europe y asia.")
        numeric = [float(weights[region]) for region in self._REGIONS]
        if any(not math.isfinite(value) or value < 0 for value in numeric):
            raise ValueError("Los pesos regionales deben ser finitos y no negativos.")
        if not math.isclose(sum(numeric), 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("Los pesos regionales deben sumar 1.")

    def _canonical_json(self, value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _required_text(self, value: str, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{field} es obligatorio.")
        return normalized

    def _aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} debe incluir zona horaria.")
        return value.astimezone(timezone.utc)