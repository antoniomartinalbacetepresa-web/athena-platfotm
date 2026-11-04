from __future__ import annotations

import math

import pytest

from app.services.recommendation_shadow_post_selection_confirmation_service import (
    RecommendationShadowPostSelectionConfirmationService,
)


class FakeIssuerRepository:
    def __init__(self, evidence_by_instrument: dict[int, dict | None]) -> None:
        self.evidence_by_instrument = evidence_by_instrument
        self.calls: list[int] = []

    def get_issuer_for_instrument(self, instrument_id: int):
        self.calls.append(instrument_id)
        return self.evidence_by_instrument.get(instrument_id)


def _evidence(issuer_id: int, confidence: float = 0.9) -> dict:
    return {
        "issuer_id": issuer_id,
        "confidence": confidence,
        "evidence_source": "sec_company_tickers",
        "resolution_method": "sec_cik",
    }


def test_post_selection_issuer_coverage_uses_confirmation_instrument_identity():
    repository = FakeIssuerRepository(
        {
            11: _evidence(101),
            12: _evidence(101),
            13: _evidence(202),
            14: None,
        }
    )
    service = RecommendationShadowPostSelectionConfirmationService(
        issuer_repository=repository
    )

    result = service._issuer_coverage(
        [
            {"instrumentId": 11},
            {"instrumentId": 12},
            {"instrumentId": 13},
            {"instrumentId": 14},
            {"instrumentId": None},
        ]
    )

    assert repository.calls == [11, 12, 13, 14]
    assert result["rowCount"] == 5
    assert result["resolvedIssuerRowCount"] == 3
    assert result["unresolvedIssuerRowCount"] == 2
    assert result["distinctResolvedIssuerCount"] == 2
    assert result["maximumRowsPerResolvedIssuer"] == 2
    assert math.isclose(result["resolvedIssuerCoverageRatio"], 3 / 5)
    assert math.isclose(result["maximumResolvedIssuerConcentrationRatio"], 2 / 3)
    assert result["statisticalIndependence"] == "not_claimed"
    assert result["thresholdsApplied"] is False


def test_post_selection_issuer_coverage_preserves_all_unresolved_fail_closed_state():
    repository = FakeIssuerRepository({21: None})
    service = RecommendationShadowPostSelectionConfirmationService(
        issuer_repository=repository
    )

    result = service._issuer_coverage([{"instrumentId": 21}, {"instrumentId": ""}])

    assert result["resolvedIssuerCoverageRatio"] == 0.0
    assert result["distinctResolvedIssuerCount"] == 0
    assert result["maximumRowsPerResolvedIssuer"] == 0
    assert result["maximumResolvedIssuerConcentrationRatio"] == 1.0
    assert result["thresholdsApplied"] is False


def test_post_selection_issuer_coverage_rejects_non_finite_identity_evidence():
    repository = FakeIssuerRepository({31: _evidence(303, confidence=float("nan"))})
    service = RecommendationShadowPostSelectionConfirmationService(
        issuer_repository=repository
    )

    with pytest.raises(ValueError, match="Evidencia issuer inválida"):
        service._issuer_coverage([{"instrumentId": 31}])


def test_post_selection_policy_keeps_issuer_metrics_observational_only():
    service = RecommendationShadowPostSelectionConfirmationService(
        issuer_repository=FakeIssuerRepository({})
    )

    policy = service._policy()

    assert policy["issuerCoverageEvidence"] == "measured_on_same_post_selection_confirmation_rows"
    assert policy["unresolvedIssuerIdentity"] == "preserved_never_inferred_from_symbol_or_name"
    assert policy["issuerCoverageThresholds"] == "not_selected_here"
    assert policy["issuerCoverageImpliesStatisticalIndependence"] is False
    assert policy["thresholdCalibration"] is False
    assert policy["automaticProductionPromotion"] is False
