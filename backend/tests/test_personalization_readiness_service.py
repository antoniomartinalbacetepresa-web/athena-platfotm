from app.services.personalization_readiness_service import (
    PersonalizationReadinessService,
)


def test_empty_profile_is_not_ready_and_never_enables_automation() -> None:
    report = PersonalizationReadinessService().evaluate(None)

    payload = report.to_api_dict()
    assert report.completion_ratio == 0.0
    assert report.optional_context_complete is False
    assert payload["missingFields"] == [
        "riskTolerance",
        "investmentHorizonYears",
        "baseCurrency",
        "objective",
        "experienceLevel",
        "liquidityNeed",
        "maxDrawdownTolerancePct",
    ]
    assert payload["automaticRecommendationOverrides"] is False
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_legacy_profile_remains_supported_but_marks_richer_context_missing() -> None:
    report = PersonalizationReadinessService().evaluate(
        {
            "riskTolerance": "balanced",
            "investmentHorizonYears": 10,
            "baseCurrency": "EUR",
            "objective": "balanced_growth",
        }
    )

    assert report.configured_fields == (
        "riskTolerance",
        "investmentHorizonYears",
        "baseCurrency",
        "objective",
    )
    assert report.missing_fields == (
        "experienceLevel",
        "liquidityNeed",
        "maxDrawdownTolerancePct",
    )
    assert report.completion_ratio == 4 / 7
    assert report.optional_context_complete is False


def test_richer_profile_reaches_complete_context_without_granting_authority() -> None:
    report = PersonalizationReadinessService().evaluate(
        {
            "riskTolerance": "growth",
            "investmentHorizonYears": 15,
            "baseCurrency": "EUR",
            "objective": "long_term_growth",
            "experienceLevel": "advanced",
            "liquidityNeed": "low",
            "maxDrawdownTolerancePct": 35,
        }
    )

    payload = report.to_api_dict()
    assert report.missing_fields == ()
    assert report.completion_ratio == 1.0
    assert report.optional_context_complete is True
    assert payload["automaticRecommendationOverrides"] is False
    assert payload["productionEligible"] is False
    assert payload["automaticTrading"] is False


def test_blank_optional_strings_are_missing_not_configured() -> None:
    report = PersonalizationReadinessService().evaluate(
        {
            "riskTolerance": "balanced",
            "investmentHorizonYears": 5,
            "baseCurrency": "EUR",
            "objective": "income",
            "experienceLevel": "   ",
            "liquidityNeed": "medium",
            "maxDrawdownTolerancePct": 20,
        }
    )

    assert "experienceLevel" in report.missing_fields
    assert "liquidityNeed" in report.configured_fields
    assert "maxDrawdownTolerancePct" in report.configured_fields
    assert report.optional_context_complete is False
