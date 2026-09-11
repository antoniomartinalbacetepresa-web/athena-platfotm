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
OWNER_A = 101
OWNER_B = 202


def repo(tmp_path):
    return RecommendationPortfolioNlvSnapshotRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )


def append(repository, **overrides):
    params = {
        "owner_user_id": OWNER_A,
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


def test_nlv_snapshot_is_idempotent_owner_scoped_and_pit_bound(tmp_path):
    repository = repo(tmp_path)
    first = append(repository)
    second = append(repository)
    assert first["id"] == second["id"]
    assert first["owner_user_id"] == OWNER_A
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
        owner_user_id=OWNER_A,
        snapshot_key=artifact["snapshotKey"],
        portfolio_id="portfolio-1",
        reporting_currency="USD",
        observed_at=OBSERVED,
        phase="regular",
        as_of=AS_OF,
    )
    assert required["artifact"] == artifact


def test_nlv_snapshot_isolated_between_owners_even_with_same_portfolio_identity(tmp_path):
    repository = repo(tmp_path)
    first = append(repository, owner_user_id=OWNER_A, value=103.2)

    with pytest.raises(ValueError, match="owner and snapshotKey"):
        repository.get_by_key(
            owner_user_id=OWNER_B,
            snapshot_key=first["snapshot_key"],
        )

    second = append(repository, owner_user_id=OWNER_B, value=104.7)
    assert second["owner_user_id"] == OWNER_B
    assert second["id"] != first["id"]
    assert second["snapshot_key"] != first["snapshot_key"]

    assert repository.get_by_key(
        owner_user_id=OWNER_A,
        snapshot_key=first["snapshot_key"],
    )["value"] == pytest.approx(103.2)
    assert repository.get_by_key(
        owner_user_id=OWNER_B,
        snapshot_key=second["snapshot_key"],
    )["value"] == pytest.approx(104.7)


def test_identical_snapshot_content_can_exist_for_two_owners_without_sharing_row(tmp_path):
    repository = repo(tmp_path)
    first = append(repository, owner_user_id=OWNER_A)
    second = append(repository, owner_user_id=OWNER_B)

    assert first["snapshot_key"] == second["snapshot_key"]
    assert first["artifact_hash"] == second["artifact_hash"]
    assert first["id"] != second["id"]
    assert first["owner_user_id"] == OWNER_A
    assert second["owner_user_id"] == OWNER_B


def test_nlv_snapshot_rejects_invalid_owner_ids(tmp_path):
    repository = repo(tmp_path)
    for invalid in (0, -1, True, 1.0, "1", None):
        with pytest.raises(ValueError, match="owner_user_id"):
            append(repository, owner_user_id=invalid)


def test_ownerless_legacy_rows_are_not_made_visible_by_v2_repository(tmp_path):
    repository = repo(tmp_path)
    repository.initialize()
    legacy_artifact = repository._artifact(
        portfolio_id="portfolio-1",
        reporting_currency="USD",
        value=103.2,
        observed_at=OBSERVED,
        available_at=OBSERVED,
        phase="regular",
        source="broker_net_liquidation_statement",
        source_ref="legacy-statement",
        as_of=AS_OF,
    )
    serialized = repository._serialize(legacy_artifact)
    import hashlib

    artifact_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    with repository._database.connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS athena_portfolio_nlv_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_key TEXT NOT NULL UNIQUE,
                portfolio_id TEXT NOT NULL,
                reporting_currency TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                phase TEXT NOT NULL,
                value REAL NOT NULL,
                source TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                artifact_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO athena_portfolio_nlv_snapshots (
                snapshot_key, portfolio_id, reporting_currency, observed_at,
                available_at, phase, value, source, source_ref, artifact_hash,
                artifact_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_artifact["snapshotKey"],
                legacy_artifact["portfolioId"],
                legacy_artifact["reportingCurrency"],
                legacy_artifact["observedAt"],
                legacy_artifact["availableAt"],
                legacy_artifact["phase"],
                legacy_artifact["value"],
                legacy_artifact["source"],
                legacy_artifact["sourceRef"],
                artifact_hash,
                serialized,
                datetime.now(UTC).isoformat(),
            ),
        )

    with pytest.raises(ValueError, match="owner and snapshotKey"):
        repository.get_by_key(
            owner_user_id=OWNER_A,
            snapshot_key=legacy_artifact["snapshotKey"],
        )


def test_nlv_snapshot_rejects_lookahead_nonfinite_and_invalid_phase(tmp_path):
    repository = repo(tmp_path)
    with pytest.raises(ValueError, match="observed_at <= available_at <= as_of"):
        append(repository, available_at=datetime(2026, 9, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="finite"):
        append(repository, value=float("nan"), source_ref="nan")
    with pytest.raises(ValueError, match="phase"):
        append(repository, phase="after_trade", source_ref="bad-phase")


def test_nlv_snapshot_provenance_conflict_fails_closed_per_owner(tmp_path):
    repository = repo(tmp_path)
    append(repository, owner_user_id=OWNER_A)
    with pytest.raises(ValueError, match="provenance"):
        append(repository, owner_user_id=OWNER_A, value=104.0)

    other_owner = append(repository, owner_user_id=OWNER_B, value=104.0)
    assert other_owner["owner_user_id"] == OWNER_B


def test_nlv_snapshot_require_rejects_wrong_identity_phase_and_asof(tmp_path):
    repository = repo(tmp_path)
    artifact = append(repository, phase="pre_external_flow")["artifact"]
    with pytest.raises(ValueError, match="another portfolio"):
        repository.require_snapshot(
            owner_user_id=OWNER_A,
            snapshot_key=artifact["snapshotKey"],
            portfolio_id="other",
            reporting_currency="USD",
            observed_at=OBSERVED,
            phase="pre_external_flow",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="phase"):
        repository.require_snapshot(
            owner_user_id=OWNER_A,
            snapshot_key=artifact["snapshotKey"],
            portfolio_id="portfolio-1",
            reporting_currency="USD",
            observed_at=OBSERVED,
            phase="post_external_flow",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="not available"):
        repository.require_snapshot(
            owner_user_id=OWNER_A,
            snapshot_key=artifact["snapshotKey"],
            portfolio_id="portfolio-1",
            reporting_currency="USD",
            observed_at=OBSERVED,
            phase="pre_external_flow",
            as_of=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_nlv_snapshot_detects_database_tampering(tmp_path):
    repository = repo(tmp_path)
    artifact = append(repository)["artifact"]
    with repository._database.connect() as connection:
        row = connection.execute(
            """
            SELECT artifact_json
            FROM athena_portfolio_nlv_snapshots_v2
            WHERE owner_user_id = ? AND snapshot_key = ?
            """,
            (OWNER_A, artifact["snapshotKey"]),
        ).fetchone()
        payload = json.loads(str(row["artifact_json"]))
        payload["value"] = 999.0
        connection.execute(
            """
            UPDATE athena_portfolio_nlv_snapshots_v2
            SET artifact_json = ?
            WHERE owner_user_id = ? AND snapshot_key = ?
            """,
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                OWNER_A,
                artifact["snapshotKey"],
            ),
        )
    with pytest.raises(ValueError):
        repository.get_by_key(
            owner_user_id=OWNER_A,
            snapshot_key=artifact["snapshotKey"],
        )
