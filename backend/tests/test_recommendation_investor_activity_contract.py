from app.services.recommendation_evidence_gate_service import RecommendationEvidenceGate


def test_investor_activity_is_connected_parallel_engine_without_unverified_evidence() -> None:
    gate = RecommendationEvidenceGate(
        status="evidence_incomplete",
        symbol="AAPL",
        as_of="2026-09-05T12:00:00+00:00",
        instrument_id=None,
        core_evidence_ready=False,
        market_evidence_ready=False,
        fundamental_evidence_ready=False,
        identity_consistent=False,
        provenance_contract_ready=False,
        data_quality_ready=False,
        valuation_ready=False,
        macro_context_ready=False,
        macro_context_valid=True,
        calibration_ready=False,
        recommendation_candidate_ready=False,
        blockers=("calibration_not_validated",),
        market={"status": "no_data"},
        fundamentals={"status": "no_data"},
        valuation={"status": "no_data"},
        macro={"status": "no_data"},
        production_eligible=False,
        reason="test",
    )

    payload = gate.to_api_dict()
    investor_activity = payload["analysisCoverage"]["investorActivity"]

    assert investor_activity == {
        "connected": True,
        "influencesCandidate": False,
        "sourceBlock": "sec13f",
        "status": "independent_parallel_engine_connected_evidence_not_bound",
        "evidenceReady": False,
        "evidenceBoundToCandidate": False,
        "pointInTimeAvailabilityVerified": False,
        "includedInAthenaRecommendation": False,
        "automaticScoring": False,
        "automaticTrading": False,
        "productionEligible": False,
    }
    assert payload["policy"]["investorActivity"] == (
        "independent_parallel_engine_connected_evidence_requires_explicit_pit_"
        "binding_not_part_of_athena_recommendation"
    )
    assert payload["productionEligible"] is False
