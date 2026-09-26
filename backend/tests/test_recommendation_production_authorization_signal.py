from __future__ import annotations

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_production_authorization_repository import (
    RecommendationProductionAuthorizationRepository,
)


FP = "a" * 64


def _draft(*, authorization_id: str, include_signal: bool = True, signal: float = 0.0123):
    draft = {
        "artifactVersion": RecommendationProductionAuthorizationRepository.ARTIFACT_VERSION,
        "authorizationId": authorization_id,
        "status": "production_recommendation_authorized",
        "productionPromotionDecisionId": "prod-decision-1",
        "productionPromotionDecisionFingerprint": FP,
        "calibratedCandidateFingerprint": FP,
        "validatedActionCandidateFingerprint": FP,
        "uncertaintyBoundActionCandidateFingerprint": FP,
        "actionPromotionDecisionId": "action-decision-1",
        "actionPromotionDecisionFingerprint": FP,
        "candidateFingerprint": FP,
        "portfolioPolicyStateFingerprint": FP,
        "economicContractFingerprint": FP,
        "instrumentId": "7",
        "symbol": "AAPL",
        "asOf": "2026-09-01T12:00:00+00:00",
        "horizonDays": 30,
        "modelFingerprint": FP,
        "policyState": "flat",
        "policyFingerprint": FP,
        "action": "buy",
        "operatorId": "operator-test",
        "authorizationReason": "Regresión de gobierno productivo con evidencia OOS.",
        "humanReviewConfirmed": True,
        "authorizationMethod": "offline_local_operator",
        "advisoryStatus": "production_recommendation",
        "recommendationCandidateReady": True,
        "productionEligible": True,
        "allocationEligible": False,
        "automaticProductionPromotion": False,
        "automaticTrading": False,
    }
    if include_signal:
        draft["expectedExcessReturn"] = signal
    return draft


def _repository(tmp_path):
    return RecommendationProductionAuthorizationRepository(
        database=AthenaDatabase(tmp_path / "athena.db")
    )


def test_persists_exact_validated_expected_excess_return(tmp_path) -> None:
    repository = _repository(tmp_path)
    record = repository.register(
        authorization_draft=_draft(authorization_id="auth-signal")
    )

    assert record["authorization"]["expectedExcessReturn"] == pytest.approx(0.0123)
    reloaded = repository.get(authorization_id="auth-signal")
    assert reloaded is not None
    assert reloaded["authorization"]["expectedExcessReturn"] == pytest.approx(0.0123)


def test_v1_authorization_without_signal_remains_valid(tmp_path) -> None:
    repository = _repository(tmp_path)
    record = repository.register(
        authorization_draft=_draft(
            authorization_id="auth-v1-compatible",
            include_signal=False,
        )
    )

    assert "expectedExcessReturn" not in record["authorization"]
    reloaded = repository.get(authorization_id="auth-v1-compatible")
    assert reloaded is not None
    assert "expectedExcessReturn" not in reloaded["authorization"]


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_rejects_non_finite_productive_signal_without_persisting(tmp_path, value) -> None:
    repository = _repository(tmp_path)
    authorization_id = f"auth-non-finite-{repr(value)}"

    with pytest.raises(ValueError, match="expectedExcessReturn debe ser finito"):
        repository.register(
            authorization_draft=_draft(
                authorization_id=authorization_id,
                signal=value,
            )
        )

    assert repository.get(authorization_id=authorization_id) is None
