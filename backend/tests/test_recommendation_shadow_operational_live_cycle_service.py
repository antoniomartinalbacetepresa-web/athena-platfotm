from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_operational_live_cycle_service import (
    RecommendationShadowOperationalLiveCycleService,
)


GATE_OLD = "a" * 64
GATE_NEW = "b" * 64


def _fp(char: str) -> str:
    return char * 64


def _row(*, horizon: int, gate: str, cutoff: str, fingerprint: str):
    return {
        "bundle_fingerprint": fingerprint,
        "research_gate_fingerprint": gate,
        "research_cutoff": cutoff,
        "horizon_days": horizon,
    }


class FakeFrozenRepository:
    def __init__(self, rows_by_horizon):
        self.rows_by_horizon = rows_by_horizon
        self.calls = []

    def list_for_horizon(self, *, horizon_days):
        self.calls.append(horizon_days)
        return [dict(row) for row in self.rows_by_horizon.get(horizon_days, [])]


class FakePersistedLiveCycleService:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "shadow_live_cycle_persisted",
            "candidateId": 10,
            "candidateFingerprint": "c" * 64,
            "policy": {
                "automaticTrading": False,
                "automaticProductionPromotion": False,
            },
            "advisoryStatus": "no_advice",
            "productionEligible": False,
            "recommendationCandidateReady": False,
        }


def _service(rows):
    repository = FakeFrozenRepository(rows)
    persisted = FakePersistedLiveCycleService()
    service = RecommendationShadowOperationalLiveCycleService(
        frozen_repository=repository,
        persisted_live_cycle_service=persisted,
    )
    return service, repository, persisted


def _as_of():
    return datetime(2026, 9, 4, tzinfo=timezone.utc)


def test_selects_latest_complete_coherent_cohort_and_forwards_exact_fingerprints():
    rows = {
        30: [
            _row(
                horizon=30,
                gate=GATE_OLD,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("1"),
            ),
            _row(
                horizon=30,
                gate=GATE_NEW,
                cutoff="2026-02-01T00:00:00+00:00",
                fingerprint=_fp("2"),
            ),
        ],
        90: [
            _row(
                horizon=90,
                gate=GATE_OLD,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("3"),
            ),
            _row(
                horizon=90,
                gate=GATE_NEW,
                cutoff="2026-02-01T00:00:00+00:00",
                fingerprint=_fp("4"),
            ),
        ],
    }
    service, repository, persisted = _service(rows)

    result = service.run(
        symbol=" aapl ",
        as_of=_as_of(),
        benchmark_symbol=" spy ",
        horizons=(30, 90),
    )

    assert repository.calls == [30, 90]
    assert persisted.calls == [
        {
            "symbol": "AAPL",
            "as_of": _as_of(),
            "bundle_fingerprints": [_fp("2"), _fp("4")],
            "benchmark_symbol": "SPY",
            "captured_at": None,
            "horizons": (30, 90),
        }
    ]
    selection = result["frozenCohortSelection"]
    assert selection["researchGateFingerprint"] == GATE_NEW
    assert selection["researchCutoff"] == "2026-02-01T00:00:00+00:00"
    assert selection["bundleFingerprints"] == [_fp("2"), _fp("4")]
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["recommendationCandidateReady"] is False
    assert result["policy"]["manualBundleFingerprintSelection"] is False
    assert result["policy"]["crossResearchGateCohortMixing"] is False


def test_newer_incomplete_cohort_is_skipped_in_favor_of_latest_complete_cohort():
    rows = {
        30: [
            _row(
                horizon=30,
                gate=GATE_OLD,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("1"),
            ),
            _row(
                horizon=30,
                gate=GATE_NEW,
                cutoff="2026-03-01T00:00:00+00:00",
                fingerprint=_fp("2"),
            ),
        ],
        90: [
            _row(
                horizon=90,
                gate=GATE_OLD,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("3"),
            )
        ],
    }
    service, _, persisted = _service(rows)

    result = service.run(
        symbol="AAPL",
        as_of=_as_of(),
        benchmark_symbol="SPY",
        horizons=(30, 90),
    )

    assert persisted.calls[0]["bundle_fingerprints"] == [_fp("1"), _fp("3")]
    assert result["frozenCohortSelection"]["researchGateFingerprint"] == GATE_OLD


def test_does_not_mix_research_gates_to_create_a_fake_complete_cohort():
    rows = {
        30: [
            _row(
                horizon=30,
                gate=GATE_OLD,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("1"),
            )
        ],
        90: [
            _row(
                horizon=90,
                gate=GATE_NEW,
                cutoff="2026-01-01T00:00:00+00:00",
                fingerprint=_fp("2"),
            )
        ],
    }
    service, _, persisted = _service(rows)

    result = service.run(
        symbol="AAPL",
        as_of=_as_of(),
        benchmark_symbol="SPY",
        horizons=(30, 90),
    )

    assert result["status"] == "shadow_operational_live_cycle_blocked"
    assert result["reason"] == "no_complete_persisted_frozen_cohort"
    assert persisted.calls == []
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False


def test_future_research_cutoff_is_never_selected():
    rows = {
        30: [
            _row(
                horizon=30,
                gate=GATE_OLD,
                cutoff="2026-10-01T00:00:00+00:00",
                fingerprint=_fp("1"),
            )
        ]
    }
    service, _, persisted = _service(rows)

    result = service.run(
        symbol="AAPL",
        as_of=_as_of(),
        benchmark_symbol="SPY",
        horizons=(30,),
    )

    assert result["status"] == "shadow_operational_live_cycle_blocked"
    assert persisted.calls == []


def test_ambiguous_selected_cohort_fails_closed_instead_of_picking_arbitrarily():
    rows = {
        30: [
            _row(
                horizon=30,
                gate=GATE_NEW,
                cutoff="2026-02-01T00:00:00+00:00",
                fingerprint=_fp("1"),
            ),
            _row(
                horizon=30,
                gate=GATE_NEW,
                cutoff="2026-02-01T00:00:00+00:00",
                fingerprint=_fp("2"),
            ),
        ]
    }
    service, _, persisted = _service(rows)

    with pytest.raises(ValueError, match="ambigua"):
        service.run(
            symbol="AAPL",
            as_of=_as_of(),
            benchmark_symbol="SPY",
            horizons=(30,),
        )
    assert persisted.calls == []


def test_naive_as_of_duplicate_horizons_and_invalid_persisted_provenance_fail_closed():
    service, _, persisted = _service({})
    with pytest.raises(ValueError, match="zona horaria"):
        service.run(
            symbol="AAPL",
            as_of=datetime(2026, 9, 4),
            benchmark_symbol="SPY",
            horizons=(30,),
        )
    with pytest.raises(ValueError, match="duplicados"):
        service.run(
            symbol="AAPL",
            as_of=_as_of(),
            benchmark_symbol="SPY",
            horizons=(30, 30),
        )

    bad, _, _ = _service(
        {
            30: [
                _row(
                    horizon=30,
                    gate="not-a-sha",
                    cutoff="2026-01-01T00:00:00+00:00",
                    fingerprint=_fp("1"),
                )
            ]
        }
    )
    with pytest.raises(ValueError, match="research gate"):
        bad.run(
            symbol="AAPL",
            as_of=_as_of(),
            benchmark_symbol="SPY",
            horizons=(30,),
        )
    assert persisted.calls == []


def test_persisted_service_cannot_escalate_shadow_contract():
    class EscalatingPersistedService(FakePersistedLiveCycleService):
        def run(self, **kwargs):
            return {
                "status": "shadow_live_cycle_persisted",
                "advisoryStatus": "buy",
                "productionEligible": True,
                "recommendationCandidateReady": True,
            }

    repository = FakeFrozenRepository(
        {
            30: [
                _row(
                    horizon=30,
                    gate=GATE_OLD,
                    cutoff="2026-01-01T00:00:00+00:00",
                    fingerprint=_fp("1"),
                )
            ]
        }
    )
    service = RecommendationShadowOperationalLiveCycleService(
        frozen_repository=repository,
        persisted_live_cycle_service=EscalatingPersistedService(),
    )

    with pytest.raises(RuntimeError, match="no_advice"):
        service.run(
            symbol="AAPL",
            as_of=_as_of(),
            benchmark_symbol="SPY",
            horizons=(30,),
        )
