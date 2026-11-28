"""Test the isolated CI fixture seed; no live data, account or provider calls."""
from datetime import datetime, timezone
from pathlib import Path
import runpy

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.market_observation_repository import MarketObservationRepository
from app.services.persisted_market_history_service import PersistedMarketHistoryService


HARNESS = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "synthetic_backend.py"


@pytest.fixture
def harness():
    # run_name avoids the CLI; global app.main was already imported by conftest,
    # so only the seed and allowlist are tested in this process.
    return runpy.run_path(str(HARNESS), run_name="synthetic_ci_seed_module")


def test_seed_is_isolated_traceable_and_exposes_no_auth_secret(tmp_path, harness):
    now = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)
    runtime = harness["prepare_state"](tmp_path / "fresh", now=now)
    assert runtime.database_path == tmp_path / "fresh" / "athena.synthetic.sqlite"
    assert runtime.manifest["instrumentId"] == 1
    assert runtime.manifest["observationCount"] == 32
    assert runtime.manifest["sourceProvider"] == "synthetic_fixture"
    secret = runtime.environment["ATHENA_AUTH_SECRET"]
    assert len(secret.encode()) >= 32
    assert secret not in repr(runtime)
    assert secret not in (runtime.state_dir / "manifest.json").read_text()
    database = AthenaDatabase(runtime.database_path)
    rows = MarketObservationRepository(database).list_for_instrument(1)
    assert len(rows) == 32
    assert all(row["source_provider"] == "synthetic_fixture" for row in rows)
    response = PersistedMarketHistoryService(database).get_history(
        instrument_id=1, source_provider="synthetic_fixture",
        observed_from=datetime.fromisoformat(runtime.manifest["observedFrom"]),
        observed_to=now, as_of=now,
    )
    assert len(response["data"]) == 32
    assert response["provenance"]["evidenceKind"] == "synthetic_fixture"
    assert response["provenance"]["licenceVerified"] is False
    assert response["provenance"]["orderExecutionAllowed"] is False


def test_seed_never_reuses_existing_state(tmp_path, harness):
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "sentinel").write_text("keep existing data")
    with pytest.raises(FileExistsError):
        harness["prepare_state"](occupied)
    assert (occupied / "sentinel").read_text() == "keep existing data"


@pytest.mark.parametrize("path,method,allowed", [
    ("/health", "GET", True),
    ("/api/v1/auth/register", "POST", True),
    ("/api/v1/auth/token", "POST", True),
    ("/api/v1/market/history/persisted", "GET", True),
    ("/api/v1/market/history/persisted", "OPTIONS", True),
    ("/api/v1/market/quote", "GET", False),
    ("/api/v1/news/feed", "GET", False),
    ("/api/v1/recommendations/professional-research/research-cycle/from-live-company-news", "POST", False),
    ("/api/v1/recommendations/professional-research/research-cycle/from-persisted-market-history", "POST", True),
    ("/api/v1/recommendations/professional-research/research-cycle/private/" + "a" * 64, "GET", True),
    ("/api/v1/recommendations/professional-research/research-cycle/private/" + "a" * 64 + "/investors-synthesis", "GET", True),
    ("/api/v1/user/account", "DELETE", False),
])
def test_allowlist_excludes_live_routes(harness, path, method, allowed):
    assert harness["SyntheticRouteAllowlist"].allowed(path, method) is allowed
