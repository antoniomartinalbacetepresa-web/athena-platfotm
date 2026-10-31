from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.incident_response_readiness import evaluate_evidence_file


def _now() -> datetime:
    return datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "incident-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_explicit_current_evidence_can_pass_without_authorizing_production(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        {
            "runbookReviewedAt": "2026-09-20T20:00:00Z",
            "exerciseCompletedAt": "2026-09-19T20:00:00+00:00",
            "incidentOwnerAssigned": True,
            "escalationChannelVerified": True,
            "credentialRevocationProcedureVerified": True,
            "recoveryProcedureVerified": True,
        },
    )

    report = evaluate_evidence_file(path, now=_now())

    assert report["ready"] is True
    assert report["productionAuthorization"] is False
    assert report["automaticTrading"] is False
    assert report["status"] == "diagnostic_only"


def test_missing_or_false_operational_evidence_fails_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "runbookReviewedAt": None,
            "exerciseCompletedAt": None,
            "incidentOwnerAssigned": False,
            "escalationChannelVerified": False,
            "credentialRevocationProcedureVerified": False,
            "recoveryProcedureVerified": False,
        },
    )

    report = evaluate_evidence_file(path, now=_now())

    assert report["ready"] is False
    assert len(report["blockers"]) == 6


def test_boolean_claims_must_be_explicit_booleans(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "runbookReviewedAt": None,
            "exerciseCompletedAt": None,
            "incidentOwnerAssigned": "true",
            "escalationChannelVerified": False,
            "credentialRevocationProcedureVerified": False,
            "recoveryProcedureVerified": False,
        },
    )

    with pytest.raises(ValueError, match="booleano explícito"):
        evaluate_evidence_file(path, now=_now())


def test_naive_timestamp_is_rejected_by_service_boundary(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "runbookReviewedAt": "2026-09-20T20:00:00",
            "exerciseCompletedAt": None,
            "incidentOwnerAssigned": True,
            "escalationChannelVerified": True,
            "credentialRevocationProcedureVerified": True,
            "recoveryProcedureVerified": True,
        },
    )

    with pytest.raises(ValueError, match="zona horaria"):
        evaluate_evidence_file(path, now=_now())
