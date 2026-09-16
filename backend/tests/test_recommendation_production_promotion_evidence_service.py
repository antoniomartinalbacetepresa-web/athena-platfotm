from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.recommendation_production_promotion_evidence_service import (
    RecommendationProductionPromotionEvidenceService,
)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _issuer_coverage(*, rows: int, resolved: int, distinct: int, maximum_rows: int) -> dict:
    return {
        "rowCount": rows,
        "resolvedIssuerRowCount": resolved,
        "unresolvedIssuerRowCount": rows - resolved,
        "resolvedIssuerCoverageRatio": resolved / rows,
        "distinctResolvedIssuerCount": distinct,
        "maximumRowsPerResolvedIssuer": maximum_rows,
        "maximumResolvedIssuerConcentrationRatio": (
            maximum_rows / resolved if resolved else 1.0
        ),
        "statisticalIndependence": "not_claimed",
        "thresholdsApplied": False,
    }


def _confirmation() -> dict:
    core = {
        "artifactVersion": "shadow-post-selection-multi-horizon-v1",
        "researchGateFingerprint": "gate-abc",
        "researchCutoff": "2026-01-31T00:00:00+00:00",
        "asOf": "2026-08-31T00:00:00+00:00",
        "requestedHorizons": [7, 30],
        "confirmedHorizonCount": 2,
        "passingHorizonCount": 2,
        "confirmationPassRatio": 1.0,
        "postSelectionProtocolEvidenceReady": True,
        "horizons": {
            "7": {
                "horizonDays": 7,
                "confirmed": True,
                "modelFingerprint": "model-7",
                "selectionFingerprint": "selection-7",
                "confirmationStart": "2026-02-01T00:00:00+00:00",
                "confirmationRowCount": 30,
                "nonOverlappingConfirmationWindowCount": 22,
                "unverifiableConfirmationWindowCount": 0,
                "issuerCoverage": _issuer_coverage(
                    rows=30, resolved=28, distinct=14, maximum_rows=2
                ),
                "metrics": {"signAccuracy": 0.60, "mse": 0.02},
                "relativeMseImprovement": 0.10,
                "beatsZeroBaselineOnMse": True,
            },
            "30": {
                "horizonDays": 30,
                "confirmed": True,
                "modelFingerprint": "model-30",
                "selectionFingerprint": "selection-30",
                "confirmationStart": "2026-02-01T00:00:00+00:00",
                "confirmationRowCount": 25,
                "nonOverlappingConfirmationWindowCount": 20,
                "unverifiableConfirmationWindowCount": 0,
                "issuerCoverage": _issuer_coverage(
                    rows=25, resolved=24, distinct=12, maximum_rows=2
                ),
                "metrics": {"signAccuracy": 0.58, "mse": 0.03},
                "relativeMseImprovement": 0.08,
                "beatsZeroBaselineOnMse": True,
            },
        },
        "thresholds": {"researchOnly": True},
    }
    return {
        **core,
        "confirmationEvidenceFingerprint": _fingerprint(core),
        "advisoryStatus": "no_advice",
        "productionEligible": False,
    }


def _protocol(service: RecommendationProductionPromotionEvidenceService) -> dict:
    core = {
        "artifactVersion": service.PROTOCOL_VERSION,
        "protocolId": "promotion-protocol-001",
        "registeredAt": "2026-01-15T00:00:00+00:00",
        "researchGateFingerprint": "gate-abc",
        "requiredHorizons": [7, 30],
        "criteriaByHorizon": {
            "7": {
                "minimumConfirmationRowCount": 20,
                "minimumNonOverlappingConfirmationWindowCount": 20,
                "minimumResolvedIssuerCoverageRatio": 0.90,
                "maximumResolvedIssuerConcentrationRatio": 0.25,
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
            "30": {
                "minimumConfirmationRowCount": 20,
                "minimumNonOverlappingConfirmationWindowCount": 18,
                "minimumResolvedIssuerCoverageRatio": 0.90,
                "maximumResolvedIssuerConcentrationRatio": 0.25,
                "minimumSignAccuracy": 0.55,
                "minimumRelativeMseImprovement": 0.05,
                "requireBeatZeroExcessMseBaseline": True,
            },
        },
    }
    return {**core, "protocolFingerprint": service.fingerprint_protocol(core)}


def _resign_confirmation(confirmation: dict) -> dict:
    core_keys = (
        "artifactVersion",
        "researchGateFingerprint",
        "researchCutoff",
        "asOf",
        "requestedHorizons",
        "confirmedHorizonCount",
        "passingHorizonCount",
        "confirmationPassRatio",
        "postSelectionProtocolEvidenceReady",
        "horizons",
        "thresholds",
    )
    core = {key: confirmation.get(key) for key in core_keys}
    confirmation["confirmationEvidenceFingerprint"] = _fingerprint(core)
    return confirmation


def test_precommitted_protocol_can_mark_evidence_ready_without_enabling_production() -> None:
    service = RecommendationProductionPromotionEvidenceService()

    result = service.evaluate(
        confirmation_artifact=_confirmation(),
        promotion_protocol=_protocol(service),
    )

    assert result["status"] == "production_promotion_evidence_ready"
    assert result["productionPromotionEvidenceReady"] is True
    assert result["advisoryStatus"] == "no_advice"
    assert result["recommendationCandidateReady"] is False
    assert result["productionEligible"] is False
    assert result["automaticProductionPromotion"] is False
    assert result["automaticTrading"] is False
    assert result["policy"]["criteriaSource"] == (
        "explicit_precommitted_protocol_no_code_defaults"
    )
    assert result["policy"]["minimumConfirmationSampleMustBePrecommitted"] is True
    assert result["policy"]["minimumTemporalBreadthMustBePrecommitted"] is True
    assert result["policy"]["unverifiableTemporalWindowsBlockPromotionEvidence"] is True
    assert result["policy"]["nonOverlappingWindowsDoNotClaimStatisticalIndependence"] is True
    assert result["policy"]["issuerCoverageMustBePrecommitted"] is True
    assert result["policy"]["issuerConcentrationMustBePrecommitted"] is True
    assert result["policy"]["issuerDiversityDoesNotClaimStatisticalIndependence"] is True
    assert result["horizons"]["7"]["minimumConfirmationRowCount"] == 20
    assert result["horizons"]["7"]["minimumNonOverlappingConfirmationWindowCount"] == 20
    assert result["horizons"]["7"]["minimumResolvedIssuerCoverageRatio"] == 0.90
    assert result["horizons"]["7"]["maximumResolvedIssuerConcentrationRatio"] == 0.25


def test_confirmation_sample_below_precommitted_minimum_fails_gate() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["confirmationRowCount"] = 19
    confirmation["horizons"]["7"]["issuerCoverage"] = _issuer_coverage(
        rows=19, resolved=18, distinct=9, maximum_rows=2
    )
    _resign_confirmation(confirmation)

    result = service.evaluate(
        confirmation_artifact=confirmation,
        promotion_protocol=_protocol(service),
    )

    assert result["productionPromotionEvidenceReady"] is False
    assert result["horizons"]["7"]["passesPrecommittedCriteria"] is False
    assert "confirmation_sample_below_precommitted_minimum" in result["horizons"]["7"]["blockers"]
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_temporal_breadth_below_precommitted_minimum_fails_gate() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["nonOverlappingConfirmationWindowCount"] = 19
    _resign_confirmation(confirmation)

    result = service.evaluate(
        confirmation_artifact=confirmation,
        promotion_protocol=_protocol(service),
    )

    assert result["productionPromotionEvidenceReady"] is False
    assert result["horizons"]["7"]["passesPrecommittedCriteria"] is False
    assert (
        "confirmation_temporal_breadth_below_precommitted_minimum"
        in result["horizons"]["7"]["blockers"]
    )
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_unverifiable_temporal_windows_fail_gate_even_when_other_metrics_pass() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["unverifiableConfirmationWindowCount"] = 1
    _resign_confirmation(confirmation)

    result = service.evaluate(
        confirmation_artifact=confirmation,
        promotion_protocol=_protocol(service),
    )

    assert result["productionPromotionEvidenceReady"] is False
    assert result["horizons"]["7"]["passesPrecommittedCriteria"] is False
    assert (
        "confirmation_contains_unverifiable_temporal_windows"
        in result["horizons"]["7"]["blockers"]
    )
    assert result["productionEligible"] is False
    assert result["automaticTrading"] is False


def test_issuer_coverage_below_precommitted_minimum_fails_gate() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["issuerCoverage"] = _issuer_coverage(
        rows=30, resolved=20, distinct=10, maximum_rows=2
    )
    _resign_confirmation(confirmation)

    result = service.evaluate(
        confirmation_artifact=confirmation,
        promotion_protocol=_protocol(service),
    )

    assert result["productionPromotionEvidenceReady"] is False
    assert "issuer_coverage_below_precommitted_minimum" in result["horizons"]["7"]["blockers"]
    assert result["productionEligible"] is False


def test_issuer_concentration_above_precommitted_maximum_fails_gate() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["issuerCoverage"] = _issuer_coverage(
        rows=30, resolved=28, distinct=14, maximum_rows=15
    )
    _resign_confirmation(confirmation)

    result = service.evaluate(
        confirmation_artifact=confirmation,
        promotion_protocol=_protocol(service),
    )

    assert result["productionPromotionEvidenceReady"] is False
    assert "issuer_concentration_above_precommitted_maximum" in result["horizons"]["7"]["blockers"]
    assert result["automaticTrading"] is False


def test_protocol_registered_after_research_cutoff_fails_closed() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    core["registeredAt"] = "2026-02-01T00:00:00+00:00"
    protocol = {**core, "protocolFingerprint": service.fingerprint_protocol(core)}

    with pytest.raises(ValueError, match="researchCutoff"):
        service.evaluate(
            confirmation_artifact=_confirmation(),
            promotion_protocol=protocol,
        )


def test_tampered_confirmation_fingerprint_fails_closed() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["metrics"]["signAccuracy"] = 0.99

    with pytest.raises(ValueError, match="modificada"):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )


def test_non_finite_confirmation_metric_fails_closed_even_if_resigned() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    confirmation["horizons"]["7"]["metrics"]["signAccuracy"] = float("nan")
    confirmation["confirmationEvidenceFingerprint"] = "re-signed"

    with pytest.raises(ValueError):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )


def test_protocol_has_no_implicit_default_thresholds() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    incomplete = {
        "artifactVersion": service.PROTOCOL_VERSION,
        "protocolId": "promotion-protocol-002",
        "registeredAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "researchGateFingerprint": "gate-abc",
        "requiredHorizons": [7],
        "criteriaByHorizon": {},
    }

    with pytest.raises(ValueError, match="Faltan criterios precomprometidos"):
        service.fingerprint_protocol(incomplete)


def test_protocol_cannot_omit_precommitted_confirmation_sample_size() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    del core["criteriaByHorizon"]["7"]["minimumConfirmationRowCount"]

    with pytest.raises(ValueError, match="minimumConfirmationRowCount"):
        service.fingerprint_protocol(core)


def test_protocol_cannot_omit_or_zero_precommitted_temporal_breadth() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    del core["criteriaByHorizon"]["7"]["minimumNonOverlappingConfirmationWindowCount"]

    with pytest.raises(ValueError, match="minimumNonOverlappingConfirmationWindowCount"):
        service.fingerprint_protocol(core)

    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    core["criteriaByHorizon"]["7"]["minimumNonOverlappingConfirmationWindowCount"] = 0

    with pytest.raises(ValueError, match="minimumNonOverlappingConfirmationWindowCount"):
        service.fingerprint_protocol(core)


def test_protocol_cannot_omit_precommitted_issuer_criteria() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    del core["criteriaByHorizon"]["7"]["minimumResolvedIssuerCoverageRatio"]
    with pytest.raises(ValueError, match="minimumResolvedIssuerCoverageRatio"):
        service.fingerprint_protocol(core)

    protocol = _protocol(service)
    core = {key: value for key, value in protocol.items() if key != "protocolFingerprint"}
    del core["criteriaByHorizon"]["7"]["maximumResolvedIssuerConcentrationRatio"]
    with pytest.raises(ValueError, match="maximumResolvedIssuerConcentrationRatio"):
        service.fingerprint_protocol(core)


def test_confirmation_cannot_omit_temporal_or_issuer_verifiability_fields() -> None:
    service = RecommendationProductionPromotionEvidenceService()
    confirmation = deepcopy(_confirmation())
    del confirmation["horizons"]["7"]["nonOverlappingConfirmationWindowCount"]
    _resign_confirmation(confirmation)

    with pytest.raises(ValueError, match="nonOverlappingConfirmationWindowCount"):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )

    confirmation = deepcopy(_confirmation())
    del confirmation["horizons"]["7"]["unverifiableConfirmationWindowCount"]
    _resign_confirmation(confirmation)

    with pytest.raises(ValueError, match="unverifiableConfirmationWindowCount"):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )

    confirmation = deepcopy(_confirmation())
    del confirmation["horizons"]["7"]["issuerCoverage"]
    _resign_confirmation(confirmation)

    with pytest.raises(ValueError, match="issuerCoverage"):
        service.evaluate(
            confirmation_artifact=confirmation,
            promotion_protocol=_protocol(service),
        )
