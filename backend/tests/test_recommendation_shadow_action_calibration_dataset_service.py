from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.recommendation_shadow_action_calibration_dataset_service import (
    RecommendationShadowActionCalibrationDatasetService,
)


CANDIDATE_FP = "c" * 64
ATTESTATION_FP = "a" * 64
DECISION_FP = "d" * 64
UNCERTAINTY_FP = "e" * 64
_DEFAULT = object()


class FakeCandidateRepository:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [_candidate_row()]

    def list_all(self):
        return [dict(row) for row in self.rows]


class FakeAttestationService:
    def __init__(self, payload=_DEFAULT):
        self.payload = _attestation() if payload is _DEFAULT else payload
        self.calls = []

    def get_for_candidate(self, *, candidate_id):
        self.calls.append(candidate_id)
        return None if self.payload is None else dict(self.payload)


class FakeDecisionService:
    def __init__(self, payload=None):
        self.payload = payload or _decision()
        self.calls = []

    def build(self, *, candidate_id):
        self.calls.append(candidate_id)
        return dict(self.payload)


class FakeEvaluationService:
    def __init__(self, payload=None):
        self.payload = payload or _evaluation()
        self.calls = []

    def evaluate(self, *, candidate_id, as_of):
        self.calls.append((candidate_id, as_of))
        return dict(self.payload)


def _candidate_row():
    return {"id": 20, "candidate_fingerprint": CANDIDATE_FP}


def _attestation():
    return {
        "status": "shadow_live_cycle_attestation_available",
        "attestationId": 2,
        "attestationFingerprint": ATTESTATION_FP,
        "candidateId": 20,
        "candidateFingerprint": CANDIDATE_FP,
        "decisionResearchFingerprint": DECISION_FP,
        "uncertaintyFingerprint": UNCERTAINTY_FP,
        "symbol": "TEST",
        "asOf": "2026-06-01T00:00:00+00:00",
        "frozenCandidateSource": "sqlite_persisted_and_revalidated",
        "callerSuppliedFrozenBundleJsonTrusted": False,
        "frozenBundleIntegrity": "gated_freeze_revalidated_after_load",
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _decision():
    return {
        "status": "shadow_live_decision_research_ready",
        "candidateId": 20,
        "candidateFingerprint": CANDIDATE_FP,
        "decisionResearchFingerprint": DECISION_FP,
        "uncertaintyFingerprint": UNCERTAINTY_FP,
        "symbol": "TEST",
        "asOf": "2026-06-01T00:00:00+00:00",
        "horizons": {
            "30": {
                "horizonDays": 30,
                "status": "decision_research_evidence_ready",
                "expectedExcessReturn": 0.06,
                "researchStrength": 1.5,
                "conservativeResearchStrength": -0.25,
                "riskAdjustedResearchStrength": 1.125,
                "uncertainty": {"rmse": 0.04, "mae": 0.03, "observationCount": 24},
                "scenarios": {
                    "lowerEmpiricalExcessReturn": -0.01,
                    "medianEmpiricalExcessReturn": 0.05,
                    "upperEmpiricalExcessReturn": 0.12,
                },
                "directionDiagnostics": {
                    "pointEstimatePositive": True,
                    "medianScenarioPositive": True,
                    "lowerScenarioPositive": False,
                    "upperScenarioNegative": False,
                },
            }
        },
        "riskContext": {
            "riskScore": 0.25,
            "annualizedVolatility": 0.30,
            "maxDrawdown60d": -0.12,
        },
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
        "actionThresholdCalibrationResearchEligible": False,
        "action": None,
        "score": None,
        "conviction": None,
    }


def _evaluation(status="evaluated"):
    horizon = {
        "horizonDays": 30,
        "status": status,
        "outcomeDueAt": "2026-07-01T00:00:00+00:00",
    }
    if status == "evaluated":
        horizon.update(
            {
                "outcomeEvaluatedAt": "2026-07-02T00:00:00+00:00",
                "realizedExcessReturn": 0.04,
                "realizedReturn": 0.05,
                "benchmarkReturn": 0.01,
                "predictionError": 0.02,
                "directionCorrect": True,
            }
        )
    return {
        "status": "shadow_live_candidate_evaluated",
        "candidateId": 20,
        "candidateFingerprint": CANDIDATE_FP,
        "symbol": "TEST",
        "candidateAsOf": "2026-06-01T00:00:00+00:00",
        "horizons": {"30": horizon},
        "advisoryStatus": "no_advice",
        "productionEligible": False,
        "recommendationCandidateReady": False,
    }


def _service(*, attestation=_DEFAULT, decision=None, evaluation=None):
    attestation_service = FakeAttestationService(attestation)
    decision_service = FakeDecisionService(decision or _decision())
    evaluation_service = FakeEvaluationService(evaluation or _evaluation())
    service = RecommendationShadowActionCalibrationDatasetService(
        candidate_repository=FakeCandidateRepository(),
        attestation_service=attestation_service,
        decision_research_service=decision_service,
        evaluation_service=evaluation_service,
    )
    return service, attestation_service, decision_service, evaluation_service


def test_dataset_admits_only_attested_ex_ante_inputs_with_matured_pit_outcome():
    service, _, _, _ = _service()
    result = service.build(
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc), horizons=[30]
    )

    assert result["status"] == "shadow_action_calibration_dataset_available"
    assert result["datasetVersion"] == "shadow-action-calibration-v2"
    assert result["rowCount"] == 1
    row = result["rows"][0]
    assert row["candidateFingerprint"] == CANDIDATE_FP
    assert row["liveCycleAttestationFingerprint"] == ATTESTATION_FP
    assert row["decisionResearchFingerprint"] == DECISION_FP
    assert row["uncertaintyFingerprint"] == UNCERTAINTY_FP
    assert row["horizonDays"] == 30
    assert row["expectedExcessReturn"] == pytest.approx(0.06)
    assert row["realizedExcessReturn"] == pytest.approx(0.04)
    assert result["policy"]["researchHoldoutReuse"] is False
    assert result["actionThresholds"] is None
    assert result["action"] is None
    assert result["score"] is None
    assert result["conviction"] is None
    assert result["productionEligible"] is False


def test_dataset_excludes_unattested_legacy_candidate_before_decision_or_outcome_access():
    service, _, decision_service, evaluation_service = _service(attestation=None)
    result = service.build(
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc), horizons=[30]
    )

    assert result["status"] == "shadow_action_calibration_dataset_pending"
    assert result["rowCount"] == 0
    assert result["unattestedCandidateCount"] == 1
    assert decision_service.calls == []
    assert evaluation_service.calls == []


def test_dataset_fails_closed_if_attestation_and_decision_fingerprints_diverge():
    attestation = _attestation()
    attestation["decisionResearchFingerprint"] = "b" * 64
    service, _, _, evaluation_service = _service(attestation=attestation)

    with pytest.raises(ValueError, match="decision research"):
        service.build(
            as_of=datetime(2026, 8, 1, tzinfo=timezone.utc), horizons=[30]
        )
    assert evaluation_service.calls == []


def test_dataset_keeps_unmatured_outcome_out_of_labels():
    service, _, _, _ = _service(evaluation=_evaluation(status="pending"))
    result = service.build(
        as_of=datetime(2026, 6, 20, tzinfo=timezone.utc), horizons=[30]
    )

    assert result["rowCount"] == 0
    assert result["pendingOutcomeRowCount"] == 1


def test_dataset_rejects_outcome_evaluated_after_requested_cutoff():
    evaluation = _evaluation()
    evaluation["horizons"]["30"]["outcomeEvaluatedAt"] = "2026-08-02T00:00:00+00:00"
    service, _, _, _ = _service(evaluation=evaluation)

    with pytest.raises(ValueError, match="futuro"):
        service.build(
            as_of=datetime(2026, 8, 1, tzinfo=timezone.utc), horizons=[30]
        )


def test_dataset_rejects_non_finite_live_features():
    decision = _decision()
    decision["horizons"]["30"]["researchStrength"] = float("nan")
    service, _, _, _ = _service(decision=decision)

    with pytest.raises(ValueError, match="finito"):
        service.build(
            as_of=datetime(2026, 8, 1, tzinfo=timezone.utc), horizons=[30]
        )
