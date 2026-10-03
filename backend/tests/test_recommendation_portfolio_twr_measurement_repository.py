from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_twr_measurement_repository import (
    RecommendationPortfolioTwrMeasurementRepository,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)
FINAL_SCHEMA = "athena_portfolio_twr_final_measurement_v1"


def _seal(payload: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(payload)
    identity = copy.deepcopy(result)
    identity.pop("measurementKey", None)
    identity["finalMeasurementSchema"] = FINAL_SCHEMA
    serialized = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    result["measurementKey"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return result


def _artifact() -> dict[str, object]:
    return _seal(
        {
            "module": "portfolio_twr_measurement",
            "status": "measured_from_canonical_server_side_portfolio_ledger",
            "measurementKey": "0" * 64,
            "ledgerMeasurementKey": "b" * 64,
            "coreMeasurementKey": "c" * 64,
            "portfolioId": "portfolio-1",
            "reportingCurrency": "EUR",
            "periodStart": START.isoformat(),
            "periodEnd": END.isoformat(),
            "asOf": AS_OF.isoformat(),
            "timeWeightedReturn": 0.21,
            "segmentReturns": [{"return": 0.1}, {"return": 0.1}],
            "boundaries": [
                {
                    "observedAt": START.isoformat(),
                    "valuationFingerprint": "1" * 64,
                },
                {
                    "observedAt": END.isoformat(),
                    "valuationFingerprint": "2" * 64,
                },
            ],
            "externalFlowTotal": 50.0,
            "externalFlowEvents": [
                {
                    "eventKey": "d" * 64,
                    "amount": 50.0,
                    "currency": "EUR",
                    "occurredAt": datetime(2026, 1, 15, tzinfo=UTC).isoformat(),
                    "availableAt": datetime(2026, 1, 15, tzinfo=UTC).isoformat(),
                    "source": "broker_statement",
                    "sourceRef": "deposit-1",
                }
            ],
            "internalCashTotals": {"cash_dividend": 2.0, "fee": -0.5, "tax": -0.25},
            "internalCashEvents": [],
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "isWeightingReady": False,
            "serverSideLedger": {
                "serverSide": True,
                "callerSuppliedEventsAccepted": False,
                "appendOnly": True,
                "tamperEvidentHashChain": True,
                "externalEventCount": 1,
                "internalEventCount": 0,
                "ledgerHeadHash": "e" * 64,
            },
            "stateIntegrity": {
                "reconciliationKey": "f" * 64,
                "portfolioStateKey": "a" * 64,
                "reconciled": True,
                "tamperVerified": True,
                "gate": "required_before_measurement",
            },
            "policy": {
                "valuationScope": "total_net_liquidation_value_in_reporting_currency",
                "callerSuppliedExternalCashFlowLedger": False,
                "callerSuppliedInternalCashEvents": False,
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
        }
    )


def _repository(tmp_path) -> RecommendationPortfolioTwrMeasurementRepository:
    return RecommendationPortfolioTwrMeasurementRepository(
        AthenaDatabase(tmp_path / "athena.sqlite3")
    )


def test_twr_repository_is_idempotent_and_binds_final_key_to_state_and_ledger(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=copy.deepcopy(artifact))

    assert first["id"] == second["id"]
    assert first["measurement_key"] == artifact["measurementKey"]
    assert first["ledger_measurement_key"] == artifact["ledgerMeasurementKey"]
    assert first["reconciliation_key"] == artifact["stateIntegrity"]["reconciliationKey"]
    assert first["ledger_head_hash"] == artifact["serverSideLedger"]["ledgerHeadHash"]
    assert len(first["artifact_hash"]) == 64

    changed_state = copy.deepcopy(artifact)
    changed_state["stateIntegrity"]["reconciliationKey"] = "1" * 64
    with pytest.raises(ValueError, match="not bound to the complete final artifact"):
        repository.append(artifact=changed_state)

    changed_ledger = copy.deepcopy(artifact)
    changed_ledger["serverSideLedger"]["ledgerHeadHash"] = "2" * 64
    with pytest.raises(ValueError, match="not bound to the complete final artifact"):
        repository.append(artifact=changed_ledger)


def test_twr_repository_rejects_return_change_without_resealing(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    changed = copy.deepcopy(artifact)
    changed["timeWeightedReturn"] = 0.99

    with pytest.raises(ValueError, match="not bound to the complete final artifact"):
        repository.append(artifact=changed)


def test_twr_repository_detects_database_tampering(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_portfolio_twr_measurements WHERE measurement_key = ?",
            (artifact["measurementKey"],),
        ).fetchone()
        tampered = json.loads(str(row["artifact_json"]))
        tampered["timeWeightedReturn"] = 0.99
        connection.execute(
            "UPDATE athena_portfolio_twr_measurements SET artifact_json = ? WHERE measurement_key = ?",
            (json.dumps(tampered, sort_keys=True, separators=(",", ":")), artifact["measurementKey"]),
        )

    with pytest.raises(ValueError):
        repository.get_by_key(measurement_key=str(artifact["measurementKey"]))


def test_require_measurement_fails_closed_on_downstream_identity_or_period_mismatch(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    record = repository.require_measurement(
        measurement_key=str(artifact["measurementKey"]),
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert record["artifact"]["timeWeightedReturn"] == pytest.approx(0.21)

    with pytest.raises(ValueError, match="another portfolio"):
        repository.require_measurement(
            measurement_key=str(artifact["measurementKey"]),
            portfolio_id="portfolio-2",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )

    with pytest.raises(ValueError, match="period_end"):
        repository.require_measurement(
            measurement_key=str(artifact["measurementKey"]),
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=datetime(2026, 2, 2, tzinfo=UTC),
            as_of=AS_OF,
        )
