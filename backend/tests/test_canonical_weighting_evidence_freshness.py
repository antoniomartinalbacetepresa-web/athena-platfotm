from datetime import datetime, timezone
from pathlib import Path

from app.database.athena_database import AthenaDatabase
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.issuer_identity_repository import IssuerIdentityRepository
from app.services.canonical_weighting_governance_service import (
    CanonicalWeightingGovernanceService,
)


PROPOSED_AT = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
APPROVED_AT = datetime(2026, 9, 14, 10, 5, tzinfo=timezone.utc)


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


def _change_us_market_cap(database: AthenaDatabase, market_cap: float) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE instruments SET market_cap = ? WHERE symbol = 'US'",
            (market_cap,),
        )


def test_approved_weights_fail_closed_when_canonical_evidence_changes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    clock = MutableClock(PROPOSED_AT)
    service = CanonicalWeightingGovernanceService(database=database, clock=clock)

    proposal = service.create_proposal(created_by="quant-operator")
    clock.value = APPROVED_AT
    service.approve_proposal(
        proposal.proposal_id,
        approved_by="risk-officer",
        approval_note="Reviewed current canonical evidence.",
    )

    active = service.get_approved_weights()
    assert active["status"] == "human_approved"
    assert active["evidenceFresh"] is True
    assert active["approvalEvidenceSha256"] == active["currentEvidenceSha256"]

    _change_us_market_cap(database, 900.0)

    stale = service.get_approved_weights()
    assert stale["status"] == "blocked_stale_evidence_requires_human_approval"
    assert stale["regionWeights"] is None
    assert stale["proposalId"] == proposal.proposal_id
    assert stale["humanApproved"] is True
    assert stale["evidenceFresh"] is False
    assert stale["approvalEvidenceSha256"] != stale["currentEvidenceSha256"]
    assert stale["automaticApproval"] is False
    assert stale["automaticTrading"] is False


def test_proposal_cannot_be_approved_after_evidence_changes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_clean_canonical_universe(database)
    clock = MutableClock(PROPOSED_AT)
    service = CanonicalWeightingGovernanceService(database=database, clock=clock)

    proposal = service.create_proposal(created_by="quant-operator")
    _change_us_market_cap(database, 900.0)
    clock.value = APPROVED_AT

    try:
        service.approve_proposal(
            proposal.proposal_id,
            approved_by="risk-officer",
            approval_note="This must not bless stale evidence.",
        )
    except ValueError as exc:
        assert "evidencia canónica cambió" in str(exc)
    else:
        raise AssertionError("Stale evidence proposal was incorrectly approved")

    proposal_after = service.get_proposal(proposal.proposal_id)
    assert proposal_after.status == "pending_human_approval"
    assert proposal_after.human_approved is False
    assert service.get_approved_weights()["status"] == "blocked_pending_human_approval"
