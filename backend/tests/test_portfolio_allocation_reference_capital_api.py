import math

import pytest
from fastapi import HTTPException

from app.api.portfolio import post_portfolio_allocation_candidate


@pytest.mark.parametrize(
    "reference_capital",
    [0, 0.0, -1, -1.0, math.nan, math.inf, -math.inf],
)
def test_allocation_candidate_rejects_non_positive_or_non_finite_reference_capital(
    reference_capital: float,
) -> None:
    payload = {
        "uncertaintyBoundActionCandidateFingerprint": "a" * 64,
        "allocationPolicyId": "policy-1",
        "referenceCapital": reference_capital,
        "baseCurrency": "EUR",
        "positions": [],
        "correlationEvidenceFingerprints": [],
        "asOf": "2026-09-12T02:00:00+00:00",
    }

    with pytest.raises(HTTPException) as exc_info:
        post_portfolio_allocation_candidate(account={"id": 7}, payload=payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "referenceCapital debe ser numérico finito y positivo."


def test_allocation_candidate_rejects_boolean_reference_capital() -> None:
    payload = {
        "uncertaintyBoundActionCandidateFingerprint": "a" * 64,
        "allocationPolicyId": "policy-1",
        "referenceCapital": True,
        "baseCurrency": "EUR",
        "positions": [],
        "correlationEvidenceFingerprints": [],
        "asOf": "2026-09-12T02:00:00+00:00",
    }

    with pytest.raises(HTTPException) as exc_info:
        post_portfolio_allocation_candidate(account={"id": 7}, payload=payload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "referenceCapital debe ser numérico finito y positivo."
