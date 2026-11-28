from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_catalyst_service import (
    RecommendationCatalystInput,
    RecommendationCatalystService,
)


AS_OF = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _catalyst(**overrides: object) -> RecommendationCatalystInput:
    values: dict[str, object] = {
        "catalyst_id": "fy26_guidance",
        "name": "FY26 guidance update",
        "kind": "guidance",
        "expected_start": datetime(2026, 1, 10, tzinfo=timezone.utc),
        "expected_end": datetime(2026, 1, 20, tzinfo=timezone.utc),
        "defined_at": datetime(2025, 12, 1, tzinfo=timezone.utc),
        "definition_source": "company_ir",
        "definition_source_ref": "ir:guidance-calendar",
    }
    values.update(overrides)
    return RecommendationCatalystInput(**values)  # type: ignore[arg-type]


def test_catalyst_pending_is_research_only_and_not_sell_advice() -> None:
    result = RecommendationCatalystService().evaluate(
        symbol=" aapl ", as_of=AS_OF, catalysts=(_catalyst(),)
    )
    payload = result.to_api_dict()

    assert result.symbol == "AAPL"
    assert result.pending_count == 1
    assert payload["catalysts"][0]["state"] == "pending"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["missedCatalystAutomaticallyInvalidatesThesis"] is False


def test_catalyst_occurrence_preserves_pit_provenance_and_timeliness() -> None:
    occurred_at = datetime(2026, 1, 22, 13, tzinfo=timezone.utc)
    available_at = occurred_at + timedelta(minutes=5)
    result = RecommendationCatalystService().evaluate(
        symbol="AAPL",
        as_of=available_at,
        catalysts=(
            _catalyst(
                occurred_at=occurred_at,
                occurrence_available_at=available_at,
                occurrence_source="company_ir",
                occurrence_source_ref="ir:release-2026-01-22",
            ),
        ),
    )

    item = result.to_api_dict()["catalysts"][0]
    assert item["state"] == "occurred"
    assert item["timeliness"] == "late"
    assert item["occurrenceAvailableAt"] == available_at.isoformat()
    assert item["occurrenceSourceRef"] == "ir:release-2026-01-22"
    assert result.delayed_count == 1


def test_catalyst_becomes_missed_only_after_expected_window_without_known_occurrence() -> None:
    result = RecommendationCatalystService().evaluate(
        symbol="AAPL",
        as_of=datetime(2026, 1, 21, tzinfo=timezone.utc),
        catalysts=(_catalyst(),),
    )
    assert result.missed_count == 1
    assert result.to_api_dict()["catalysts"][0]["state"] == "missed"


def test_catalyst_rejects_lookahead_for_definition_and_occurrence_evidence() -> None:
    service = RecommendationCatalystService()
    with pytest.raises(ValueError, match="defined_at.*look-ahead"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(_catalyst(defined_at=AS_OF + timedelta(seconds=1)),),
        )

    with pytest.raises(ValueError, match="occurrence_available_at.*look-ahead"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(
                _catalyst(
                    occurred_at=AS_OF,
                    occurrence_available_at=AS_OF + timedelta(seconds=1),
                    occurrence_source="company_ir",
                    occurrence_source_ref="ir:event",
                ),
            ),
        )


def test_catalyst_requires_complete_occurrence_provenance() -> None:
    service = RecommendationCatalystService()
    with pytest.raises(ValueError, match="completa"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(_catalyst(occurred_at=AS_OF),),
        )


def test_catalyst_rejects_duplicate_identity_bad_windows_and_unknown_kinds() -> None:
    service = RecommendationCatalystService()
    with pytest.raises(ValueError, match="no puede repetirse"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(_catalyst(), _catalyst(name="Duplicate")),
        )
    with pytest.raises(ValueError, match="expected_end"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(
                _catalyst(
                    expected_start=datetime(2026, 1, 20, tzinfo=timezone.utc),
                    expected_end=datetime(2026, 1, 10, tzinfo=timezone.utc),
                ),
            ),
        )
    with pytest.raises(ValueError, match="kind"):
        service.evaluate(
            symbol="AAPL", as_of=AS_OF, catalysts=(_catalyst(kind="rumor"),)
        )


def test_catalyst_rejects_naive_timestamps_and_occurrence_time_after_availability() -> None:
    service = RecommendationCatalystService()
    with pytest.raises(ValueError, match="as_of.*zona horaria"):
        service.evaluate(
            symbol="AAPL", as_of=datetime(2026, 1, 15), catalysts=(_catalyst(),)
        )
    with pytest.raises(ValueError, match="occurred_at no puede ser posterior"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            catalysts=(
                _catalyst(
                    occurred_at=AS_OF,
                    occurrence_available_at=AS_OF - timedelta(seconds=1),
                    occurrence_source="company_ir",
                    occurrence_source_ref="ir:event",
                ),
            ),
        )
