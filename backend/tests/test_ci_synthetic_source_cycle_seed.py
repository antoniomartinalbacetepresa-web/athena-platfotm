"""Future-owner fixtures exist only in a new explicitly isolated CI database."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import runpy

import pytest

from app.api import recommendation_professional_research_cycle as api
from app.database.athena_database import AthenaDatabase
from app.repositories.persisted_market_research_reference_repository import PersistedMarketResearchReferenceRepository
from app.repositories.recommendation_investment_journal_repository import RecommendationInvestmentJournalRepository
from app.repositories.recommendation_professional_research_cycle_repository import RecommendationProfessionalResearchCycleRepository
from app.repositories.user_account_repository import UserAccountRepository
from app.repositories.auth_security_repository import AuthSecurityRepository
from app.services.persisted_market_history_service import PersistedMarketHistoryService
from app.services.auth_service import AuthService


def test_future_owner_sources_have_pit_metadata_and_no_precreated_accounts(tmp_path, monkeypatch):
    harness = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/ci/synthetic_backend.py"))
    runtime = harness["prepare_state"](tmp_path / "fresh", now=datetime.now(timezone.utc) - timedelta(minutes=5))
    database = AthenaDatabase(runtime.database_path)
    for name, factory in (
        ("journal_repository", RecommendationInvestmentJournalRepository),
        ("cycle_repository", RecommendationProfessionalResearchCycleRepository),
        ("market_reference_repository", PersistedMarketResearchReferenceRepository),
        ("persisted_history_service", PersistedMarketHistoryService),
    ):
        monkeypatch.setattr(api, name, factory(database))
    hashes = harness["seed_source_cycles"](runtime)
    assert set(hashes) == {"news", "investors"}
    assert runtime.manifest["futureOwnerFixtureId"] == 1
    assert runtime.manifest["accountsSeeded"] is False
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM athena_user_accounts").fetchone()[0] == 0
    records, _ = api.cycle_repository.list_private(owner_id=1, symbol="SYNTH")
    assert len(records) == 2
    assert api.cycle_repository.list_private(owner_id=2)[0] == []
    for category, digest in hashes.items():
        package = api.cycle_repository.get_by_hash(cycle_hash=digest, owner_id=1)["package"]
        evidence = package["radar"]["candidates"][0]["evidence"][0]
        assert evidence["category"] == category
        assert evidence["provider"] == "synthetic_fixture"
        assert evidence["publisher"].startswith("SYNTHETIC")
        assert evidence["summary"].startswith("SYNTHETIC")
        assert evidence["sourceRef"] == f"https://synthetic.invalid/ci/{category}"
        assert datetime.fromisoformat(evidence["publishedAt"]) <= datetime.fromisoformat(evidence["availableAt"]) <= datetime.fromisoformat(package["cycle"]["asOf"])
        assert package["cycle"]["advisoryStatus"] == "no_advice"
        assert package["cycle"]["productionEligible"] is package["cycle"]["policy"]["automaticTrading"] is False
        for owner in (None, 2):
            with pytest.raises(ValueError):
                api.cycle_repository.get_by_hash(cycle_hash=digest, owner_id=owner)
    # Real registration still allocates the first identity, rather than a
    # seeded credential or manually assigned account ID.
    service = AuthService(repository=UserAccountRepository(database), security_repository=AuthSecurityRepository(database), secret_key="synthetic-ci-test-secret-with-at-least-32-bytes")
    account = service.register(email="synthetic@example.invalid", password="Synthetic-Only-Password-2026!")
    assert account["id"] == 1
    with pytest.raises(RuntimeError, match="unused"):
        harness["seed_source_cycles"](runtime)
