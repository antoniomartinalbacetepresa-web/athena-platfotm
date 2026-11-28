"""Ephemeral loopback FastAPI harness for browser/SQLite acceptance.

Usage from repository root:
    python scripts/ci/synthetic_backend.py --state-dir "$RUNNER_TEMP/athena-ci" --port 8000

The state directory must not already exist. No credentials or provider data are
seeded. Tests register synthetic users through the real auth API. The process
creates a fresh random JWT secret, installs its database environment BEFORE
importing app.main, and allows only local auth/persisted-research routes.
Two artificial private source cycles belong to futureOwnerFixtureId=1: only
the first real test registration in this new isolated database receives them.
No account, password, token, external news or investor filing is pre-created.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


@dataclass(frozen=True)
class SyntheticRuntime:
    state_dir: Path
    database_path: Path
    manifest: dict
    environment: dict[str, str] = field(repr=False)


def prepare_state(state_dir: Path, *, now: datetime | None = None) -> SyntheticRuntime:
    """Create a new synthetic catalogue/history; never reuse or overwrite a DB."""
    root = Path(state_dir).resolve()
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.utcoffset() is None:
        raise ValueError("Synthetic clock requires an explicit timezone.")
    instant = instant.astimezone(timezone.utc)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    database_path = root / "athena.synthetic.sqlite"
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.database.athena_database import AthenaDatabase
    from app.repositories.instrument_repository import InstrumentRepository
    from app.repositories.market_observation_repository import MarketObservationRepository

    database = AthenaDatabase(database_path)
    database.initialize()
    instrument_id = InstrumentRepository(database).upsert({
        "symbol": "SYNTH", "companyName": "Synthetic CI fixture only",
        "exchangeShortName": "TEST", "currency": "USD",
        "instrumentType": "common_stock", "sourceProvider": "synthetic_fixture",
    })
    sessions = []
    day = instant.date() - timedelta(days=1)
    while len(sessions) < 32:
        if day.weekday() < 5:
            sessions.append(datetime(day.year, day.month, day.day, 21, tzinfo=timezone.utc))
        day -= timedelta(days=1)
    sessions.reverse()
    retrieved = instant - timedelta(seconds=1)
    # Every session is before today; timestamps are fixture declarations, not
    # a claim about an exchange's actual hours, calendar or publication clock.
    observations = [{
        "timestamp": session, "source_timestamp": session,
        "open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0,
        "volume": 1000 + index,
    } for index, session in enumerate(sessions)]
    stats = MarketObservationRepository(database).save_many(
        instrument_id=instrument_id, observations=observations,
        source_provider="synthetic_fixture", retrieved_at=retrieved,
    )
    if stats.inserted != 32 or instrument_id != 1:
        raise RuntimeError("Unexpected synthetic seed identity or row count.")
    manifest = {
        "schema": "athena.synthetic-ci.v1", "syntheticOnly": True,
        "instrumentId": instrument_id, "symbol": "SYNTH", "currency": "USD",
        "exchange": "TEST", "sourceProvider": "synthetic_fixture",
        "observationCount": stats.inserted,
        "observedFrom": sessions[0].isoformat(), "observedTo": sessions[-1].isoformat(),
        "retrievedAt": retrieved.isoformat(), "seededAt": instant.isoformat(),
        "licenceVerified": False, "productionEligible": False,
        "automaticTrading": False, "accountsSeeded": False,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return SyntheticRuntime(root, database_path, manifest, {
        "ATHENA_DATABASE_PATH": str(database_path),
        "ATHENA_AUTH_SECRET": secrets.token_urlsafe(48),
        "ATHENA_ENV": "ci_synthetic",
        "ATHENA_PORTFOLIO_EVENT_LEDGER_PATH": str(root / "synthetic-ledger.jsonl"),
    })


class SyntheticRouteAllowlist:
    """Exercise real routes while excluding live-provider/account-mutation flows.

    This is an inbound test harness boundary, not a production network sandbox.
    None of its allowed routes invokes an external market/news/model provider.
    """
    AUTH = {
        "/api/v1/auth/register": {"POST"}, "/api/v1/auth/token": {"POST"},
        "/api/v1/auth/me": {"GET"}, "/api/v1/auth/logout": {"POST"},
        "/api/v1/auth/logout-all": {"POST"},
    }
    RESEARCH_PREFIX = "/api/v1/recommendations/professional-research"

    def __init__(self, app):
        self.app = app

    @classmethod
    def allowed(cls, path: str, method: str) -> bool:
        permitted = cls.AUTH.get(path)
        if permitted is not None:
            return method in permitted or method == "OPTIONS"
        if path == "/health" or path == "/api/v1/market/history/persisted":
            return method in {"GET", "OPTIONS"}
        if path == "/api/v1/research/strategies/rebound25/synthetic-backtest":
            return method in {"POST", "OPTIONS"}
        artifacts = "/api/v1/research/strategies/rebound25/artifacts"
        if path == artifacts:
            return method in {"GET", "POST", "OPTIONS"}
        if re.fullmatch(re.escape(artifacts) + r"/[a-f0-9]{64}", path):
            return method in {"GET", "OPTIONS"}
        if re.fullmatch(re.escape(artifacts) + r"/[a-f0-9]{64}/research-cycle", path):
            return method in {"POST", "OPTIONS"}
        if path == cls.RESEARCH_PREFIX + "/research-cycle/from-persisted-market-history":
            return method in {"POST", "OPTIONS"}
        if method not in {"GET", "OPTIONS"}:
            return False
        suffix = path.removeprefix(cls.RESEARCH_PREFIX)
        if suffix == path:
            return False
        return bool(
            suffix == "/research-cycle/private"
            or re.fullmatch(r"/research-cycle/private/[a-f0-9]{64}(?:/(?:news|investors|athena)-synthesis)?", suffix)
            or re.fullmatch(r"/research-cycle/[a-f0-9]{64}", suffix)
            or re.fullmatch(r"/market-history-reference/private/[a-f0-9]{64}", suffix)
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self.allowed(scope["path"], scope["method"]):
            from starlette.responses import JSONResponse
            response = JSONResponse({"detail": "Route excluded from synthetic CI harness."}, status_code=404)
            await response(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


def seed_source_cycles(runtime: SyntheticRuntime) -> dict[str, str]:
    """Trusted fresh-CI fixture, never an account bootstrap or ingestion API."""
    from app.api import recommendation_professional_research_cycle as api
    from app.database.athena_database import AthenaDatabase
    from app.repositories.user_account_repository import UserAccountRepository

    expected = runtime.database_path.resolve()
    if (runtime.manifest.get("schema") != "athena.synthetic-ci.v1"
            or runtime.manifest.get("syntheticOnly") is not True
            or expected.parent != runtime.state_dir.resolve()
            or any(store._database.database_path.resolve() != expected for store in (
                api.journal_repository, api.cycle_repository, api.market_reference_repository,
                api.persisted_history_service,
            ))):
        raise RuntimeError("Source fixtures require the exact isolated synthetic database.")
    database = AthenaDatabase(expected)
    UserAccountRepository(database)  # Schema only; no account or credential.
    api.cycle_repository.initialize()
    with database.connect() as connection:
        if (connection.execute("SELECT COUNT(*) FROM athena_user_accounts").fetchone()[0]
                or connection.execute("SELECT COUNT(*) FROM athena_professional_research_cycles").fetchone()[0]
                or connection.execute("SELECT 1 FROM sqlite_sequence WHERE name = 'athena_user_accounts' AND seq > 0").fetchone()):
            raise RuntimeError("Source fixtures require unused accounts and research stores.")
        listing = connection.execute("SELECT symbol, source_provider FROM instruments WHERE id = 1").fetchone()
        if listing is None or listing["symbol"] != "SYNTH" or listing["source_provider"] != "synthetic_fixture":
            raise RuntimeError("Source fixtures require the synthetic listing identity.")
    instant = datetime.fromisoformat(runtime.manifest["seededAt"])
    as_of = instant - timedelta(seconds=10)
    available = instant - timedelta(minutes=1)
    published = instant - timedelta(minutes=2)
    hashes = {}
    for category in ("news", "investors"):
        request = api.ProfessionalResearchCycleRequest(
            instrumentId="1", symbol="SYNTH", asOf=as_of, recordedAt=as_of,
            journalId=f"__athena_private_owner_1__:ci-synthetic-{category}", revisionId="r1",
            thesis=f"SYNTHETIC CI {category} fixture; no real source or market claim.",
            radarEvidence=[{
                "evidenceId": f"ci-synthetic-{category}", "category": category, "urgency": "routine",
                "summary": f"SYNTHETIC CI {category} fixture; invented metadata, no financial claim.",
                "availableAt": available, "publishedAt": published,
                "source": "synthetic_fixture", "provider": "synthetic_fixture",
                "publisher": "SYNTHETIC CI artificial publisher",
                "sourceRef": f"https://synthetic.invalid/ci/{category}",
            }],
            journalReferences=[{
                "referenceId": f"ci-artificial-context-{category}", "kind": "assumption",
                "availableAt": available, "source": "synthetic_fixture",
                "sourceRef": f"urn:synthetic:ci:human-context:{category}",
            }],
            contradictoryEvidence=[{
                "evidenceId": f"ci-artificial-objection-{category}", "kind": "alternative_explanation",
                "claim": "SYNTHETIC: artificial evidence cannot establish market performance or data rights.",
                "strength": "material", "availableAt": available, "source": "synthetic_fixture",
                "sourceRef": f"urn:synthetic:ci:human-objection:{category}",
            }],
        )
        result = api._persist_professional_research_cycle(request, owner_id=1)["data"]
        hashes[category] = result["integrity"]["cycleHash"]
    runtime.manifest.update({"futureOwnerFixtureId": 1, "sourceCycleHashes": hashes})
    (runtime.state_dir / "manifest.json").write_text(json.dumps(runtime.manifest, sort_keys=True) + "\n", encoding="utf-8")
    return hashes


def create_application(runtime: SyntheticRuntime):
    if "app.main" in sys.modules:
        raise RuntimeError("Start the synthetic backend in a fresh process before importing app.main.")
    os.environ.update(runtime.environment)
    # Avoid inherited proxy credentials/optional SOCKS requirements in this
    # process. Allowed fixture routes use SQLite only, never remote providers.
    for key in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        os.environ.pop(key, None)
    from app.main import app
    seed_source_cycles(runtime)
    return SyntheticRouteAllowlist(app)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--port", default=8000, type=int)
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("port must be between 1 and 65535")
    runtime = prepare_state(arguments.state_dir)
    app = create_application(runtime)
    # The manifest contains fixture metadata only; JWT secret stays in memory.
    print(json.dumps({"syntheticManifest": str(runtime.state_dir / "manifest.json"),
                      "baseUrl": f"http://127.0.0.1:{arguments.port}"}), flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()
