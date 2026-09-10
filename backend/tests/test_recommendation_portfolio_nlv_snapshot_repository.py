from datetime import datetime, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_nlv_snapshot_repository import (
    RecommendationPortfolioNlvSnapshotRepository,
)


UTC = timezone.utc
OBSERVED = datetime(2026, 8, 31, 12, tzinfo=UTC)
AS_OF = datetime(2026, 9, 1, 12, tzinfo=UTC)


def repo(tmp_path):
    return RecommendationPortfolioNlvSnapshotRepository(AthenaDatabase(tmp_path / "athena.sqlite3"))


def append(repository, **overrides):
    params = {
        "portfolio_id": "portfolio-1",
        "reporting_currency": "USD",
        "value": 103.2,
        "observed_at": OBSERVED,
        "available_at": OBSERVED,
        "phase": "regular",
        "source": "broker_net_liquidation_statement",
        "source_ref": "statement:2026-08-31:regular",
        "as_of": AS_OF,
    }
    params.update(overrides)
    return repository.append(**params)


def test_nlv_snapshot_is_idempotent_and_pit_bound(tmp_path):
    repository = repo(tmp_path)
    first = append(repository)
    second = append(repository)
    assert first["id"] == second["id"]
    artifact = first["artifact"]
    assert len(artifact["snapshotKey"]) == 64
    assert artifact["valuationScope"] == "total_net_liquidation_value_in_reporting_currency"
    assert artifact["advisoryStatus"] == "no_advice"
    assert artifact["productionEligible"] is False
    assert artifact["isWeightingReady"] is False
    assert artifact["policy"]["cashInference"] == "forbidden"
    assert artifact["policy"]["liabilityInference"] == "forbidden"
    assert artifact["policy"]["unsettledInference"] == "forbidden"
    assert artifact["policy"]["fxInference"] == "forbidden"

    required = repository.require_snapshot(
        snapshot_key=artifact["snapshotKey"],
        portfolio_id="portfolio-1",
        reporting_currency="USD",
        observed_at=OBSERVED,
        phase="regular",
        as_of=AS_OF,
    )
    assert required["artifact"] == artifact


def test_nlv_snapshot_rejects_lookahead_nonfinite_and_invalid_phase(tmp_path):
    repository = repo(tmp_path)
    with pytest.raises(ValueError, match="observed_at <= available_at <= as_of"):
        append(repository, available_at=datetime(2026, 9, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="finite"):
        append(repository, value=float("nan"), source_ref="nan")
    with pytest.raises(ValueError, match="phase"):
        append(repository, phase="after_trade", source_ref="bad-phase")


def test_nlv_snapshot_provenance_conflict_fails_closed(tmp_path):
    repository = repo(tmp_path)
    append(repository)
    with pytest.raises(ValueError, match="provenance"):
        append(repository, value=104.0)


def test_nlv_snapshot_require_rejects_wrong_identity_phase_and_asof(tmp_path):
    repository = repo(tmp_path)
    artifact = append(repository, phase="pre_external_flow")["artifact"]
    with pytest.raises(ValueError, match="another portfolio"):
        repository.require_snapshot(
            snapshot_key=artifact["snapshotKey"], portfolio_id="other", reporting_currency="USD",
            observed_at=OBSERVED, phase="pre_external_flow", as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="phase"):
        repository.require_snapshot(
            snapshot_key=artifact["snapshotKey"], portfolio_id="portfolio-1", reporting_currency="USD",
            observed_at=OBSERVED, phase="post_external_flow", as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="not available"):
        repository.require_snapshot(
            snapshot_key=artifact["snapshotKey"], portfolio_id="portfolio-1", reporting_currency="USD",
            observed_at=OBSERVED, phase="pre_external_flow", as_of=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_nlv_snapshot_detects_database_tampering(tmp_path):
    repository = repo(tmp_path)
    artifact = append(repository)["artifact"]
    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_portfolio_nlv_snapshots WHERE snapshot_key = ?",
            (artifact["snapshotKey"],),
        ).fetchone()
        payload = json.loads(str(row["artifact_json"]))
        payload["value"] = 999.0
        connection.execute(
            "UPDATE athena_portfolio_nlv_snapshots SET artifact_json = ? WHERE snapshot_key = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), artifact["snapshotKey"]),
        )
    with pytest.raises(ValueError):
        repository.get_by_key(snapshot_key=artifact["snapshotKey"])
