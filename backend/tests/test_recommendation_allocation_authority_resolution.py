from datetime import datetime, timezone

from app.services.recommendation_allocation_authority_resolution_service import (
    RecommendationAllocationAuthorityResolutionService,
)


AS_OF = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)
ACTION_FP = "a" * 64
ACTION_RECORD_FP = "b" * 64
CORR_FP = "c" * 64


class FakeIndex:
    def __init__(self, *, actions=(ACTION_FP,), correlations=(CORR_FP,)):
        self.actions = actions
        self.correlations = correlations

    def action_fingerprints(self, *, instrument_id, as_of):
        assert instrument_id == 7
        assert as_of == AS_OF
        return self.actions

    def correlation_fingerprints(self, *, left_instrument_id, right_instrument_id, as_of):
        assert {left_instrument_id, right_instrument_id} == {7, 9}
        assert as_of == AS_OF
        return self.correlations


class FakeActionRepository:
    def get(self, *, candidate_fingerprint):
        if candidate_fingerprint != ACTION_FP:
            return None
        return {
            "record_fingerprint": ACTION_RECORD_FP,
            "artifact": {
                "instrumentId": 7,
                "horizonDays": 30,
                "asOf": AS_OF.isoformat(),
                "advisoryStatus": "no_advice",
                "recommendationCandidateReady": False,
                "productionEligible": False,
                "allocationEligible": False,
                "automaticTrading": False,
            },
        }


class FakeCorrelationRepository:
    def get(self, *, evidence_fingerprint):
        if evidence_fingerprint != CORR_FP:
            return None
        return {
            "artifact": {
                "leftInstrumentId": 7,
                "rightInstrumentId": 9,
                "knowledgeCutoff": AS_OF.isoformat(),
                "advisoryStatus": "no_advice",
                "productionEligible": False,
                "allocationEligible": False,
                "automaticTrading": False,
            },
        }


def _service(index):
    return RecommendationAllocationAuthorityResolutionService(
        index=index,
        action_repository=FakeActionRepository(),
        correlation_repository=FakeCorrelationRepository(),
    )


def test_resolves_exact_persisted_authorities_without_selecting_policy():
    result = _service(FakeIndex()).resolve(
        instrument_id=7,
        horizon_days=30,
        held_instrument_ids=[7, 9],
        as_of=AS_OF,
    )
    assert result["allocationAuthoritiesReady"] is True
    assert result["uncertaintyBoundActionCandidateFingerprint"] == ACTION_FP
    assert result["correlationEvidenceFingerprints"] == [CORR_FP]
    assert result["callerSuppliedInternalFingerprintsRequired"] is False
    assert result["policySelectionPerformed"] is False
    assert result["economicContractInvented"] is False
    assert result["advisoryStatus"] == "no_advice"
    assert result["productionEligible"] is False
    assert result["allocationEligible"] is False
    assert result["automaticTrading"] is False


def test_missing_action_fails_closed_as_not_ready():
    result = _service(FakeIndex(actions=())).resolve(
        instrument_id=7,
        horizon_days=30,
        held_instrument_ids=[7, 9],
        as_of=AS_OF,
    )
    assert result["allocationAuthoritiesReady"] is False
    assert result["reason"] == "action_authority_missing"
    assert "uncertaintyBoundActionCandidateFingerprint" not in result


def test_ambiguous_action_fails_closed_instead_of_choosing_latest():
    result = _service(FakeIndex(actions=(ACTION_FP, "d" * 64))).resolve(
        instrument_id=7,
        horizon_days=30,
        held_instrument_ids=[7],
        as_of=AS_OF,
    )
    assert result["allocationAuthoritiesReady"] is False
    assert result["reason"] == "action_authority_ambiguous"


def test_missing_correlation_fails_closed():
    result = _service(FakeIndex(correlations=())).resolve(
        instrument_id=7,
        horizon_days=30,
        held_instrument_ids=[9],
        as_of=AS_OF,
    )
    assert result["allocationAuthoritiesReady"] is False
    assert result["reason"] == "correlation_authority_missing:9"


def test_duplicate_held_instruments_are_rejected():
    try:
        _service(FakeIndex()).resolve(
            instrument_id=7,
            horizon_days=30,
            held_instrument_ids=[9, 9],
            as_of=AS_OF,
        )
    except ValueError as exc:
        assert "duplicados" in str(exc)
    else:
        raise AssertionError("Expected duplicate held instruments to fail closed")
