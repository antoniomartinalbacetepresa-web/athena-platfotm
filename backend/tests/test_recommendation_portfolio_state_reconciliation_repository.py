from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_state_reconciliation_repository import (
    RecommendationPortfolioStateReconciliationRepository,
)


AS_OF = datetime(2026, 2, 2, tzinfo=timezone.utc)


def artifact(*, reconciled: bool = True, portfolio_id: str = "portfolio-1") -> dict[str, object]:
    key_seed = "a" if reconciled else "b"
    return {
        "reconciliationKey": key_seed * 64,
        "portfolioStateKey": "c" * 64,
        "portfolioId": portfolio_id,
        "reportingCurrency": "EUR",
        "asOf": AS_OF.isoformat(),
        "snapshotObservedAt": AS_OF.isoformat(),
        "snapshotAvailableAt": AS_OF.isoformat(),
        "reconciled": reconciled,
        "cashDifference": 0.0 if reconciled else 1.0,
        "positionMismatches": [],
        "snapshotProvenance": {
            "source": "independent_broker_snapshot",
            "sourceRef": "urn:broker:portfolio-1:2026-02-02",
        },
        "policy": {
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "stateMismatchAction": "fail_closed",
            "cashInference": "forbidden",
            "fxInference": "forbidden",
            "snapshotRequired": True,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
    }


def test_repository_is_append_only_idempotent_and_requires_reconciled(tmp_path: Path) -> None:
    repository = RecommendationPortfolioStateReconciliationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    first = repository.append(artifact=artifact())
    second = repository.append(artifact=artifact())
    assert first["reconciliation_key"] == second["reconciliation_key"] == "a" * 64

    gated = repository.require_reconciled(
        reconciliation_key="a" * 64,
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        as_of=AS_OF,
    )
    assert gated["artifact"]["reconciled"] is True

    repository.append(artifact=artifact(reconciled=False))
    with pytest.raises(ValueError, match="reconciled=true"):
        repository.require_reconciled(
            reconciliation_key="b" * 64,
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            as_of=AS_OF,
        )


def test_repository_rejects_cross_portfolio_currency_and_time_reuse(tmp_path: Path) -> None:
    repository = RecommendationPortfolioStateReconciliationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    repository.append(artifact=artifact())

    with pytest.raises(ValueError, match="otra cartera"):
        repository.require_reconciled(
            reconciliation_key="a" * 64,
            portfolio_id="portfolio-2",
            reporting_currency="EUR",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="otra moneda"):
        repository.require_reconciled(
            reconciliation_key="a" * 64,
            portfolio_id="portfolio-1",
            reporting_currency="USD",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="exactamente al as_of"):
        repository.require_reconciled(
            reconciliation_key="a" * 64,
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            as_of=datetime(2026, 2, 3, tzinfo=timezone.utc),
        )


def test_repository_detects_direct_sqlite_tampering(tmp_path: Path) -> None:
    database = AthenaDatabase(tmp_path / "athena.db")
    repository = RecommendationPortfolioStateReconciliationRepository(database)
    record = repository.append(artifact=artifact())

    with database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_portfolio_state_reconciliations WHERE reconciliation_key = ?",
            (record["reconciliation_key"],),
        ).fetchone()
        mutated = json.loads(str(row["artifact_json"]))
        mutated["reconciled"] = False
        connection.execute(
            "UPDATE athena_portfolio_state_reconciliations SET artifact_json = ? WHERE reconciliation_key = ?",
            (
                json.dumps(mutated, sort_keys=True, separators=(",", ":"), allow_nan=False),
                record["reconciliation_key"],
            ),
        )

    with pytest.raises(ValueError, match="modificado"):
        repository.get_by_key(reconciliation_key=record["reconciliation_key"])


def test_repository_rejects_unsafe_contract(tmp_path: Path) -> None:
    repository = RecommendationPortfolioStateReconciliationRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )
    unsafe = artifact()
    unsafe["productionEligible"] = True
    with pytest.raises(ValueError, match="producción"):
        repository.append(artifact=unsafe)
