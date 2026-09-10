from datetime import datetime, timezone
import json

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_reconciled_portfolio_weight_repository import (
    RecommendationReconciledPortfolioWeightRepository,
)
from app.services.recommendation_reconciled_portfolio_weight_service import (
    RecommendationReconciledPortfolioWeightService,
)


UTC = timezone.utc
AS_OF = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _artifact(*, cash_weight: float = 0.0) -> dict[str, object]:
    service = RecommendationReconciledPortfolioWeightService()
    positions = [
        {
            "instrumentId": 101,
            "symbol": "AAA",
            "quantity": 6.0,
            "positionValueInReportingCurrency": 60.0,
            "canonicalIdentity": {"instrumentId": 101},
            "price": 10.0,
            "priceSourceProvider": "official_market_source",
            "priceObservedAt": AS_OF.isoformat(),
            "priceRetrievedAt": AS_OF.isoformat(),
            "fx": {"rate": 1.0, "historicalPointInTimeEligible": True},
            "weight": 0.6 if cash_weight == 0.0 else 0.5,
        },
        {
            "instrumentId": 202,
            "symbol": "BBB",
            "quantity": 4.0,
            "positionValueInReportingCurrency": 40.0,
            "canonicalIdentity": {"instrumentId": 202},
            "price": 10.0,
            "priceSourceProvider": "official_market_source",
            "priceObservedAt": AS_OF.isoformat(),
            "priceRetrievedAt": AS_OF.isoformat(),
            "fx": {"rate": 1.0, "historicalPointInTimeEligible": True},
            "weight": 0.4 if cash_weight == 0.0 else 0.4,
        },
    ]
    core = {
        "artifactVersion": service.ARTIFACT_VERSION,
        "portfolioId": "portfolio-weights-test",
        "asOf": AS_OF.isoformat(),
        "reportingCurrency": "USD",
        "reconciliationKey": "1" * 64,
        "portfolioStateKey": "2" * 64,
        "portfolioValuationEvidenceFingerprint": "3" * 64,
        "cashBalance": 0.0 if cash_weight == 0.0 else 10.0,
        "cashWeight": cash_weight,
        "investedPositionsValue": 100.0 if cash_weight == 0.0 else 90.0,
        "totalPortfolioValue": 100.0,
        "positions": positions,
        "snapshotProvenance": {
            "observedAt": AS_OF.isoformat(),
            "availableAt": AS_OF.isoformat(),
            "source": "independent_broker_snapshot",
            "sourceRef": "urn:test:weights:snapshot",
        },
    }
    return {
        "module": "reconciled_portfolio_weights",
        "status": "diagnostic_weights_derived_from_reconciled_state_and_pit_valuation",
        **core,
        "weightEvidenceKey": service._fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "isWeightingReady": False,
        "allocationEligible": False,
        "automaticTrading": False,
        "policy": {
            "weightDerivation": "reconciled_quantities_plus_sealed_pit_valuation_plus_explicit_cash",
            "cash": "from_independent_reconciled_snapshot_never_inferred",
            "prices": "from_sealed_pit_valuation",
            "fx": "from_sealed_pit_valuation_never_implicitly_converted",
            "positionIdentity": "exact_instrument_set_and_quantity_match_required",
            "missingEvidence": "fail_closed",
            "automaticTrading": False,
            "automaticProductionPromotion": False,
            "automaticModelMutation": False,
            "allocationAuthority": "not_granted_diagnostic_weights_only",
        },
    }


def _repository(tmp_path) -> RecommendationReconciledPortfolioWeightRepository:
    return RecommendationReconciledPortfolioWeightRepository(
        database=AthenaDatabase(tmp_path / "athena-weights.sqlite3")
    )


def test_append_read_and_identical_replay_are_idempotent(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()

    first = repository.append(artifact=artifact)
    second = repository.append(artifact=artifact)
    loaded = repository.get_by_key(weight_evidence_key=artifact["weightEvidenceKey"])

    assert first["id"] == second["id"] == loaded["id"]
    assert loaded["artifact"] == artifact
    assert len(loaded["artifact_hash"]) == 64
    assert loaded["artifact"]["advisoryStatus"] == "no_advice"
    assert loaded["artifact"]["productionEligible"] is False
    assert loaded["artifact"]["isWeightingReady"] is False
    assert loaded["artifact"]["automaticTrading"] is False
    assert loaded["artifact"]["policy"]["automaticProductionPromotion"] is False


def test_require_weight_evidence_binds_portfolio_currency_and_exact_asof(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    record = repository.require_weight_evidence(
        weight_evidence_key=artifact["weightEvidenceKey"],
        portfolio_id="portfolio-weights-test",
        reporting_currency="USD",
        as_of=AS_OF,
    )
    assert record["artifact"]["weightEvidenceKey"] == artifact["weightEvidenceKey"]

    with pytest.raises(ValueError, match="otra cartera"):
        repository.require_weight_evidence(
            weight_evidence_key=artifact["weightEvidenceKey"],
            portfolio_id="other",
            reporting_currency="USD",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="otra moneda"):
        repository.require_weight_evidence(
            weight_evidence_key=artifact["weightEvidenceKey"],
            portfolio_id="portfolio-weights-test",
            reporting_currency="EUR",
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="exactamente"):
        repository.require_weight_evidence(
            weight_evidence_key=artifact["weightEvidenceKey"],
            portfolio_id="portfolio-weights-test",
            reporting_currency="USD",
            as_of=datetime(2026, 8, 2, 12, tzinfo=UTC),
        )


def test_detects_artifact_json_tampering(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    with repository._database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_json FROM athena_reconciled_portfolio_weight_evidence WHERE weight_evidence_key = ?",
            (artifact["weightEvidenceKey"],),
        ).fetchone()
        body = json.loads(row["artifact_json"])
        body["positions"][0]["weight"] = 0.61
        connection.execute(
            "UPDATE athena_reconciled_portfolio_weight_evidence SET artifact_json = ? WHERE weight_evidence_key = ?",
            (json.dumps(body, sort_keys=True, separators=(",", ":")), artifact["weightEvidenceKey"]),
        )

    with pytest.raises(ValueError, match="modificado|no suma"):
        repository.get_by_key(weight_evidence_key=artifact["weightEvidenceKey"])


def test_detects_indexed_column_tampering(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact()
    repository.append(artifact=artifact)

    with repository._database.connect() as connection:
        connection.execute(
            "UPDATE athena_reconciled_portfolio_weight_evidence SET portfolio_id = 'other' WHERE weight_evidence_key = ?",
            (artifact["weightEvidenceKey"],),
        )

    with pytest.raises(ValueError, match="portfolio_id"):
        repository.get_by_key(weight_evidence_key=artifact["weightEvidenceKey"])


def test_cash_remains_part_of_denominator_and_is_not_renormalized(tmp_path) -> None:
    repository = _repository(tmp_path)
    artifact = _artifact(cash_weight=0.1)

    record = repository.append(artifact=artifact)
    stored = record["artifact"]
    position_weight_sum = sum(float(item["weight"]) for item in stored["positions"])

    assert stored["cashWeight"] == pytest.approx(0.1)
    assert position_weight_sum == pytest.approx(0.9)
    assert position_weight_sum + stored["cashWeight"] == pytest.approx(1.0)
