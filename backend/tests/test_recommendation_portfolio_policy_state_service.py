import pytest

from app.services.recommendation_portfolio_policy_state_service import (
    RecommendationPortfolioPolicyStateService,
)


def test_flat_requires_explicit_absence_of_position():
    service = RecommendationPortfolioPolicyStateService()
    artifact = service.build(
        instrument_id=7,
        canonical_instrument_id="instrument:7",
        policy_state="flat",
        position_present=False,
        shares=0.0,
        identity_risk_ready=True,
        identity_exchange_verified=True,
    )

    assert artifact["policyState"] == "flat"
    assert artifact["positionPresent"] is False
    assert artifact["productionEligible"] is False
    assert artifact["automaticTrading"] is False
    assert artifact["policy"]["reducedVsFullExposureInferredFromShares"] is False


def test_non_flat_state_requires_real_positive_position():
    service = RecommendationPortfolioPolicyStateService()

    with pytest.raises(ValueError, match="posición real"):
        service.build(
            instrument_id=7,
            canonical_instrument_id="instrument:7",
            policy_state="full_long",
            position_present=False,
            shares=0.0,
            identity_risk_ready=True,
            identity_exchange_verified=True,
        )


def test_unverified_identity_cannot_enter_action_state():
    service = RecommendationPortfolioPolicyStateService()

    with pytest.raises(ValueError, match="identidad canónica"):
        service.build(
            instrument_id=7,
            canonical_instrument_id="instrument:7",
            policy_state="reduced_long",
            position_present=True,
            shares=4.0,
            identity_risk_ready=False,
            identity_exchange_verified=True,
        )


def test_non_finite_shares_fail_closed():
    service = RecommendationPortfolioPolicyStateService()

    with pytest.raises(ValueError, match="finito"):
        service.build(
            instrument_id=7,
            canonical_instrument_id="instrument:7",
            policy_state="full_long",
            position_present=True,
            shares=float("nan"),
            identity_risk_ready=True,
            identity_exchange_verified=True,
        )
