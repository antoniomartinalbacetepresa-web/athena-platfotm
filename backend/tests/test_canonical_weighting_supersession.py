from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_weighting_governance_service import CanonicalWeightingGovernanceService


NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


def _seed(database: AthenaDatabase) -> None:
    instruments = InstrumentRepository(database=database)
    identities = IssuerIdentityRepository(database=database)
    for symbol, cap, country, region in (
        ("US", 600.0, "United States", "america"),
        ("DE", 300.0, "Germany", "europe"),
        ("JP", 100.0, "Japan", "asia"),
    ):
        instrument_id = instruments.upsert({
            "symbol": symbol, "companyName": symbol, "country": country,
            "regionKey": region, "exchangeShortName": symbol, "currency": "USD",
            "instrumentType": "EQUITY", "marketCap": cap, "isPrimaryListing": True,
        })
        issuer_id = identities.upsert_external_issuer(
            source_provider="official", external_id=f"{symbol}-ISSUER",
            canonical_name=symbol, evidence_confidence=1.0,
            domicile_country=country, region_key=region,
        )
        identities.link_instrument(
            instrument_id=instrument_id, issuer_id=issuer_id,
            evidence_source="official", resolution_method="official_identifier", confidence=1.0,
        )


def _service(tmp_path: Path) -> CanonicalWeightingGovernanceService:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    _seed(database)
    return CanonicalWeightingGovernanceService(database=database, clock=lambda: NOW)


def test_new_pending_proposal_supersedes_older_human_approval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.create_proposal(created_by="quant-a")
    service.approve_proposal(first.proposal_id, approved_by="risk-a", approval_note="reviewed")
    assert service.get_approved_weights()["status"] == "human_approved"

    second = service.create_proposal(created_by="quant-b")
    blocked = service.get_approved_weights()

    assert blocked["status"] == "blocked_pending_human_approval"
    assert blocked["proposalId"] == second.proposal_id
    assert blocked["proposalStatus"] == "pending_human_approval"
    assert blocked["regionWeights"] is None
    assert blocked["humanApproved"] is False


def test_rejected_latest_proposal_does_not_reactivate_older_approval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.create_proposal(created_by="quant-a")
    service.approve_proposal(first.proposal_id, approved_by="risk-a", approval_note="reviewed")
    second = service.create_proposal(created_by="quant-b")
    service.reject_proposal(second.proposal_id, rejected_by="risk-b", rejection_note="not accepted")

    blocked = service.get_approved_weights()
    assert blocked["proposalId"] == second.proposal_id
    assert blocked["proposalStatus"] == "rejected"
    assert blocked["regionWeights"] is None


def test_superseded_pending_proposal_cannot_be_approved(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.create_proposal(created_by="quant-a")
    second = service.create_proposal(created_by="quant-b")

    with pytest.raises(ValueError, match="sustituida"):
        service.approve_proposal(first.proposal_id, approved_by="risk-a", approval_note="late")

    approved = service.approve_proposal(second.proposal_id, approved_by="risk-b", approval_note="current")
    assert approved.human_approved is True
    assert service.get_approved_weights()["proposalId"] == second.proposal_id
