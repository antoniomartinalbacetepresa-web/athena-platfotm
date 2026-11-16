from datetime import datetime, timezone
import pytest

from app.services.pilot_history_coverage import assess_pilot_history
from app.services.pilot_observation_contract import UnverifiedMarketObservation

AS_OF = datetime(2026, 11, 9, tzinfo=timezone.utc)


def bar(day):
    return dict(instrument_id="TEST:MSFT", symbol="MSFT", source="test",
                license_reference="test-only", license_verified=True,
                observation_at=f"2026-11-{day:02d}T21:00:00Z",
                available_at=f"2026-11-{day:02d}T21:01:00Z",
                retrieved_at="2026-11-08T12:00:00Z", currency="USD",
                close="100", volume="100", adjustment_status="raw", bar_status="closed")


def test_reports_gaps_without_claiming_operational_coverage():
    result = assess_pilot_history([bar(3), bar(6)], as_of=AS_OF)
    assert result["calendar_gaps"] == [{"from": "2026-11-04", "to": "2026-11-05", "calendar_days": 2}]
    assert result["production_coverage_claimed"] is False
    assert result["minimum_span_met"] is False


@pytest.mark.parametrize("bars", [
    [], [bar(6), bar(3)], [bar(3), bar(3)], [dict(bar(3), currency="EUR"), bar(6)]
])
def test_rejects_missing_unordered_duplicate_or_mixed_history(bars):
    with pytest.raises(UnverifiedMarketObservation):
        assess_pilot_history(bars, as_of=AS_OF)
