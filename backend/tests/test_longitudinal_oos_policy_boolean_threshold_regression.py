from __future__ import annotations

import pytest

from app.services.longitudinal_oos_sufficiency_policy_service import (
    LongitudinalOosSufficiencyPolicyService,
)


def _criteria() -> dict[str, object]:
    return {
        "minimumEvaluationSpanDays": 30,
        "minimumDistinctEvaluationPeriods": 3,
        "minimumEligibleOutcomes": 10,
        "minimumDistinctResolvedIssuers": 4,
        "requiredHorizonSeconds": [604800, 2592000],
        "dependencyHandling": "issuer_clustered_test_only",
    }


@pytest.mark.parametrize("value", [True, False])
def test_boolean_span_threshold_is_not_a_numeric_policy_threshold(value: bool) -> None:
    criteria = _criteria()
    criteria["minimumEvaluationSpanDays"] = value

    with pytest.raises(ValueError, match="minimumEvaluationSpanDays"):
        LongitudinalOosSufficiencyPolicyService.fingerprint(
            policy_id="boolean-threshold-must-fail",
            version=1,
            criteria=criteria,
        )
