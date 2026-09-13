from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_weighting_governance_service import (
    CanonicalWeightingGovernanceService,
)


CREATED_AT = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)
APPROVED_AT = datetime(2026, 9, 13, 20, 5, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _database(tmp_path: Path) -> AthenaDatabase:
    database = AthenaDatabase(tmp_path / "athena.db")
    database.initialize()
    return database


def _seed_clean_canonical_universe(database: AthenaDatabase) -> None:
    instruments = InstrumentRepository(database=database)
    identities = IssuerIdentityRepository(database=database)
    fixtures = (
        ("US", 600.0, "United States", "america", "US-ISSUER"),
        ("DE", 300.0, "Germany", "europe", "DE-ISSUER"),
        ("JP", 100.0, "Japan", "asia", "JP-ISSUER"),
    )
    for symbol, cap, country, region, external_id in fixtures:
        instrument_id = instruments.upsert(
            {
                "symbol": symbol,
                "companyName": symbol,
                "country": country,
                "regionKey": region,
                "exchangeShortName": symbol,
                "currency": "USD",
                "instrumentType": "EQUITY",
                "marketCap": cap,
                "isPrimaryListing": True,
            }
        )
        issuer_id = identities.upsert_external_issuer(
            source_provider="official",
            external_id=external_id,
            canonical_name=symbol,
            evidence_confidence=1.0,
            domicile_country=country,
            region_key=region,
        )
        identities.link_instrument(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )


def test_proposal_is_pending_and_cannot_be_consumed_without_human_approval(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    service = CanonicalWeightingGovernanceService(
        database=database,
        clock=lambda: CREATED_AT,
    )

    proposal = service.create_proposal(created_by="quant-operator")

    assert proposal.status == "pending_human_approval"
    assert proposal.human_approved is False
    assert proposal.region_weights == pytest.approx(
        {"america": 0.6, "europe": 0.3, "asia": 0.1}
    )
    blocked = service.get_approved_weights()
    assert blocked == {
        "status": "blocked_pending_human_approval",
        "regionWeights": None,
        "proposalId": None,
        "humanApproved": False,
        "automaticApproval": False,
        "automaticTrading": False,
    }


def test_explicit_distinct_human_approval_unlocks_exact_immutable_weights(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    clock = MutableClock(CREATED_AT)
    service = CanonicalWeightingGovernanceService(database=database, clock=clock)
    proposal = service.create_proposal(created_by="quant-operator")
    original_hash = proposal.evidence_sha256

    clock.value = APPROVED_AT
    approved = service.approve_proposal(
        proposal.proposal_id,
        approved_by="risk-officer",
        approval_note="Revisado contra identidad, domicilio y capitalización canónica.",
    )

    assert approved.status == "approved"
    assert approved.human_approved is True
    assert approved.evidence_sha256 == original_hash
    active = service.get_approved_weights()
    assert active["status"] == "human_approved"
    assert active["proposalId"] == proposal.proposal_id
    assert active["approvedBy"] == "risk-officer"
    assert active["regionWeights"] == pytest.approx(
        {"america": 0.6, "europe": 0.3, "asia": 0.1}
    )
    assert active["automaticApproval"] is False
    assert active["automaticTrading"] is False


def test_self_approval_and_empty_approval_reason_are_rejected(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    service = CanonicalWeightingGovernanceService(
        database=database,
        clock=lambda: CREATED_AT,
    )
    proposal = service.create_proposal(created_by="same-person")

    with pytest.raises(ValueError, match="separación de funciones"):
        service.approve_proposal(
            proposal.proposal_id,
            approved_by="SAME-PERSON",
            approval_note="checked",
        )
    with pytest.raises(ValueError, match="approval_note"):
        service.approve_proposal(
            proposal.proposal_id,
            approved_by="reviewer",
            approval_note="   ",
        )
    assert service.get_approved_weights()["humanApproved"] is False


def test_rejection_never_unlocks_weighting(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    service = CanonicalWeightingGovernanceService(
        database=database,
        clock=lambda: CREATED_AT,
    )
    proposal = service.create_proposal(created_by="quant-operator")

    rejected = service.reject_proposal(
        proposal.proposal_id,
        rejected_by="risk-officer",
        rejection_note="Cobertura externa aún no aceptada operacionalmente.",
    )

    assert rejected.status == "rejected"
    assert rejected.human_approved is False
    assert service.get_approved_weights()["status"] == "blocked_pending_human_approval"
    with pytest.raises(ValueError, match="pendiente"):
        service.approve_proposal(
            proposal.proposal_id,
            approved_by="other-reviewer",
            approval_note="late approval",
        )


def test_proposal_fails_closed_when_canonical_evidence_is_incomplete(tmp_path: Path) -> None:
    database = _database(tmp_path)
    instruments = InstrumentRepository(database=database)
    identities = IssuerIdentityRepository(database=database)
    instrument_id = instruments.upsert(
        {
            "symbol": "AMB-A",
            "companyName": "Ambiguous",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NASDAQ",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 100.0,
        }
    )
    second_id = instruments.upsert(
        {
            "symbol": "AMB-B",
            "companyName": "Ambiguous",
            "country": "United States",
            "regionKey": "america",
            "exchangeShortName": "NYSE",
            "currency": "USD",
            "instrumentType": "EQUITY",
            "marketCap": 200.0,
        }
    )
    issuer_id = identities.upsert_external_issuer(
        source_provider="official",
        external_id="AMBIGUOUS",
        canonical_name="Ambiguous",
        evidence_confidence=1.0,
        domicile_country="United States",
        region_key="america",
    )
    for candidate in (instrument_id, second_id):
        identities.link_instrument(
            instrument_id=candidate,
            issuer_id=issuer_id,
            evidence_source="official",
            resolution_method="official_identifier",
            confidence=1.0,
        )

    service = CanonicalWeightingGovernanceService(
        database=database,
        clock=lambda: CREATED_AT,
    )
    with pytest.raises(ValueError, match="fallback de mediana"):
        service.create_proposal(created_by="quant-operator")


def test_tampered_evidence_fails_integrity_check(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    service = CanonicalWeightingGovernanceService(
        database=database,
        clock=lambda: CREATED_AT,
    )
    proposal = service.create_proposal(created_by="quant-operator")

    with database.connect() as connection:
        connection.execute(
            "UPDATE canonical_weighting_proposals SET evidence_snapshot_json = ? WHERE id = ?",
            ('{"regionWeights":{"america":1.0,"europe":0.0,"asia":0.0}}', proposal.proposal_id),
        )

    with pytest.raises(RuntimeError, match="SHA-256"):
        service.get_proposal(proposal.proposal_id)
