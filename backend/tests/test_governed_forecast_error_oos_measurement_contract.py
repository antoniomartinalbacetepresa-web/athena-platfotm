from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.governed_forecast_error_oos_service import GovernedForecastErrorOosService


class _MeasurementService:
    def __init__(self, measurement):
        self.measurement = measurement

    def evaluate(self, **_kwargs):
        return self.measurement


class _Repository:
    def get_latest_policy(self, *, as_of):
        return None


class _PolicyService:
    def evaluate(self, **_kwargs):
        raise AssertionError("Malformed evidence must be rejected before policy evaluation")


def _measurement():
    return {
        "evaluationSpanDays": 40.0,
        "distinctEvaluationPeriodCount": 4,
        "eligibleOutcomeCount": 12,
        "forecastErrorCount": 12,
        "distinctResolvedIssuerCount": 5,
        "horizons": {
            "604800": {"forecastErrorCount": 6},
            "2592000": {"forecastErrorCount": 6},
        },
    }


def _service(measurement):
    return GovernedForecastErrorOosService(
        measurement_service=_MeasurementService(measurement),
        policy_service=_PolicyService(),
        policy_repository=_Repository(),
    )


@pytest.mark.parametrize("invalid_span", [float("inf"), float("-inf"), float("nan"), -1.0, True])
def test_non_finite_or_invalid_span_cannot_reach_longitudinal_policy(invalid_span):
    measurement = _measurement()
    measurement["evaluationSpanDays"] = invalid_span

    with pytest.raises(RuntimeError, match="evaluationSpanDays"):
        _service(measurement).evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            cohort_record=None,
            error_records=[],
        )


@pytest.mark.parametrize(
    "field,invalid_value",
    [
        ("distinctEvaluationPeriodCount", True),
        ("eligibleOutcomeCount", 12.5),
        ("forecastErrorCount", -1),
        ("distinctResolvedIssuerCount", "5"),
    ],
)
def test_malformed_counts_cannot_be_coerced_into_governed_evidence(field, invalid_value):
    measurement = _measurement()
    measurement[field] = invalid_value

    with pytest.raises(RuntimeError, match=field):
        _service(measurement).evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            cohort_record=None,
            error_records=[],
        )


def test_malformed_horizon_error_count_fails_closed_before_policy_evaluation():
    measurement = _measurement()
    measurement["horizons"]["2592000"]["forecastErrorCount"] = True

    with pytest.raises(RuntimeError, match="horizons.2592000.forecastErrorCount"):
        _service(measurement).evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            cohort_record=None,
            error_records=[],
        )


def test_total_forecast_errors_cannot_exceed_eligible_outcomes():
    measurement = _measurement()
    measurement["forecastErrorCount"] = 13
    measurement["horizons"]["604800"]["forecastErrorCount"] = 7

    with pytest.raises(RuntimeError, match="más forecast errors"):
        _service(measurement).evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            cohort_record=None,
            error_records=[],
        )


def test_horizon_forecast_errors_must_reconcile_with_total():
    measurement = _measurement()
    measurement["horizons"]["2592000"]["forecastErrorCount"] = 5

    with pytest.raises(RuntimeError, match="no reconcilia"):
        _service(measurement).evaluate(
            as_of=datetime(2026, 3, 1, tzinfo=timezone.utc),
            cohort_record=None,
            error_records=[],
        )
