from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_live_candidate_evaluation_service import (
    RecommendationShadowLiveCandidateEvaluationService,
)


class _CandidateRepository:
    def __init__(self, stored):
        self._stored = stored

    def get(self, candidate_id):
        return deepcopy(self._stored)


class _SnapshotRepository:
    def __init__(self, outcomes, *, snapshot=None):
        self._outcomes = outcomes
        self._snapshot = snapshot or _snapshot()

    def get_snapshot(self, snapshot_id):
        return deepcopy(self._snapshot)

    def list_outcomes(self, snapshot_id):
        return deepcopy(self._outcomes)


class _CandidateService:
    def validate_artifact(self, artifact):
        return artifact


def _candidate():
    return {
        "status": "shadow_live_candidate_inferred",
        "candidateFingerprint": "c" * 64,
        "symbol": "TEST",
        "asOf": "2025-06-01T00:00:00+00:00",
        "horizons": {
            "7": {
                "horizonDays": 7,
                "expectedExcessReturn": 0.05,
            }
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _snapshot():
    return {
        "id": 10,
        "instrument_id": 7,
        "symbol": "TEST",
        "data_cutoff_at": "2025-06-01T00:00:00+00:00",
        "entry_price": 100.0,
        "entry_observed_at": "2025-06-01T00:00:00+00:00",
        "entry_retrieved_at": "2025-06-01T00:00:00+00:00",
        "benchmark_symbol": "SPY",
        "evidence_snapshot": {
            "market": {
                "symbol": "TEST",
                "instrumentId": 7,
                "asOf": "2025-06-01T00:00:00+00:00",
                "latestPrice": 100.0,
                "latestObservedAt": "2025-06-01T00:00:00+00:00",
                "latestRetrievedAt": "2025-06-01T00:00:00+00:00",
                "sourceProviders": ["asset_test"],
            }
        },
    }


def _outcome(*, realized_return=0.04, benchmark_return=0.01, excess_return=0.03, exit_price=104.0):
    return {
        "horizon_days": 7,
        "due_at": "2025-06-08T00:00:00+00:00",
        "evaluated_at": "2025-06-09T00:00:00+00:00",
        "exit_price": exit_price,
        "exit_observed_at": "2025-06-08T00:00:00+00:00",
        "exit_retrieved_at": "2025-06-09T00:00:00+00:00",
        "source_provider": "asset_test",
        "realized_return": realized_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
        "benchmark_evidence": {
            "status": "resolved",
            "benchmarkSymbol": "SPY",
            "benchmarkInstrumentId": 44,
            "entryPrice": 100.0,
            "exitPrice": 101.0,
            "benchmarkReturn": 0.01,
            "entryObservedAt": "2025-06-01T00:00:00+00:00",
            "exitObservedAt": "2025-06-08T00:00:00+00:00",
            "entryRetrievedAt": "2025-06-01T00:01:00+00:00",
            "exitRetrievedAt": "2025-06-09T00:00:00+00:00",
            "entrySourceProvider": "benchmark_test",
            "exitSourceProvider": "benchmark_test",
        },
    }


def _service(outcome, *, snapshot=None):
    return RecommendationShadowLiveCandidateEvaluationService(
        candidate_repository=_CandidateRepository(
            {"id": 20, "snapshot_id": 10, "artifact": _candidate()}
        ),
        snapshot_repository=_SnapshotRepository([outcome], snapshot=snapshot),
        candidate_service=_CandidateService(),
    )


def _evaluate(service):
    return service.evaluate(
        candidate_id=20,
        as_of=datetime(2025, 6, 10, tzinfo=timezone.utc),
    )


def test_tampered_excess_return_fails_closed():
    with pytest.raises(ValueError, match="excess_return no coincide"):
        _evaluate(_service(_outcome(excess_return=0.20)))


def test_non_finite_realized_return_fails_closed():
    with pytest.raises(ValueError, match="realized_return debe ser finito"):
        _evaluate(_service(_outcome(realized_return=float("inf"))))


def test_coordinated_return_tampering_is_detected_from_preserved_prices():
    with pytest.raises(ValueError, match="realized_return no coincide con los precios PIT"):
        _evaluate(
            _service(
                _outcome(
                    realized_return=0.20,
                    excess_return=0.19,
                )
            )
        )


def test_ambiguous_entry_provider_fails_closed():
    snapshot = _snapshot()
    snapshot["evidence_snapshot"]["market"]["sourceProviders"] = [
        "asset_test",
        "another_provider",
    ]
    with pytest.raises(ValueError, match="provenance exacta.*ambigua"):
        _evaluate(_service(_outcome(), snapshot=snapshot))


def test_asset_exit_observation_before_due_fails_closed():
    outcome = _outcome()
    outcome["exit_observed_at"] = "2025-06-07T23:59:59+00:00"
    with pytest.raises(ValueError, match="salida del activo está fuera"):
        _evaluate(_service(outcome))


def test_asset_identity_mismatch_fails_closed():
    snapshot = _snapshot()
    snapshot["evidence_snapshot"]["market"]["instrumentId"] = 8
    with pytest.raises(ValueError, match="otro instrumento"):
        _evaluate(_service(_outcome(), snapshot=snapshot))


def test_consistent_return_identity_remains_shadow_only():
    result = _evaluate(_service(_outcome()))

    horizon = result["horizons"]["7"]
    assert horizon["status"] == "evaluated"
    assert horizon["realizedReturn"] == pytest.approx(0.04)
    assert horizon["benchmarkReturn"] == pytest.approx(0.01)
    assert horizon["realizedExcessReturn"] == pytest.approx(0.03)
    assert horizon["assetEvidence"] == {
        "symbol": "TEST",
        "instrumentId": 7,
        "entryPrice": 100.0,
        "exitPrice": 104.0,
        "realizedReturn": pytest.approx(0.04),
        "entryObservedAt": "2025-06-01T00:00:00+00:00",
        "exitObservedAt": "2025-06-08T00:00:00+00:00",
        "entryRetrievedAt": "2025-06-01T00:00:00+00:00",
        "exitRetrievedAt": "2025-06-09T00:00:00+00:00",
        "entrySourceProvider": "asset_test",
        "exitSourceProvider": "asset_test",
    }
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert (
        result["policy"]["targetIntegrity"]
        == "realized_return_reconstructed_from_frozen_entry_and_persisted_exit_prices_then_excess_recomputed"
    )
    assert result["policy"]["automaticProductionPromotion"] is False
