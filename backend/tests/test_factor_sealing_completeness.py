from __future__ import annotations

from app.api import recommendation_factor_risk as legacy_factor_risk
from app.api import recommendation_factor_risk_candidate_impact as legacy_candidate_impact
from app.api import recommendation_factor_risk_sealed_value as sealed_api
from app.main import app
from app.services import recommendation_factor_risk_service as factor_service


EXPECTED_FACTORS = {
    "market",
    "size",
    "value",
    "momentum",
    "quality",
    "low_volatility",
    "rates",
    "usd_fx",
}
FUNDAMENTAL_FACTORS = {"value", "quality"}


def test_public_factor_sealing_partition_covers_every_core_factor_exactly() -> None:
    core = set(factor_service._ALLOWED_FACTORS)
    legacy_sealed = set(legacy_factor_risk._SEALED_CALLER_FORBIDDEN)
    wrapper_sealed = set(FUNDAMENTAL_FACTORS)

    assert core == EXPECTED_FACTORS
    assert legacy_sealed == EXPECTED_FACTORS - FUNDAMENTAL_FACTORS
    assert wrapper_sealed == FUNDAMENTAL_FACTORS
    assert legacy_sealed.isdisjoint(wrapper_sealed)
    assert legacy_sealed | wrapper_sealed == core


def test_candidate_impact_sealing_partition_matches_factor_risk() -> None:
    legacy_candidate_sealed = set(legacy_candidate_impact._SEALED_CALLER_FORBIDDEN)
    assert legacy_candidate_sealed == EXPECTED_FACTORS - FUNDAMENTAL_FACTORS
    assert legacy_candidate_sealed | FUNDAMENTAL_FACTORS == EXPECTED_FACTORS


def test_public_factor_risk_routes_have_no_legacy_bypass() -> None:
    schema = app.openapi()["paths"]
    factor_path = "/api/v1/recommendations/professional-research/factor-risk"
    candidate_path = factor_path + "/candidate-impact"

    assert set(schema[factor_path]) == {"post"}
    assert set(schema[candidate_path]) == {"post"}
    assert schema[factor_path]["post"]["operationId"].startswith(
        "post_factor_risk_with_sealed_value_"
    )
    assert schema[candidate_path]["post"]["operationId"].startswith(
        "post_candidate_impact_with_value_block_"
    )


def test_public_models_do_not_restore_caller_weights_or_required_free_factors() -> None:
    factor_fields = sealed_api.SealedValueFactorRiskPositionRequest.model_fields
    baseline_fields = sealed_api.SealedCandidateBaselineRequest.model_fields
    candidate_fields = sealed_api.SealedCandidateRequest.model_fields

    assert "weight" not in factor_fields
    assert "weight" not in baseline_fields
    assert "weight" in candidate_fields  # explicit hypothetical cash-funded scenario only

    assert factor_fields["factors"].default_factory is dict
    assert baseline_fields["factors"].default_factory is dict
    assert candidate_fields["factors"].default_factory is dict

    for fields in (factor_fields, baseline_fields, candidate_fields):
        assert "valueExposureKey" in fields
        assert "qualityExposureKey" in fields


def test_sealed_factor_derivation_contracts_are_explicit_and_non_advisory() -> None:
    assert sealed_api._reject_free_fundamentals is not None
    assert sealed_api._load_value is not None
    assert sealed_api._load_quality is not None

    # Public fundamental factors are keys to persisted artifacts, never raw scores.
    factor_fields = sealed_api.SealedValueFactorRiskPositionRequest.model_fields
    assert factor_fields["valueExposureKey"].annotation == str | None
    assert factor_fields["qualityExposureKey"].annotation == str | None
