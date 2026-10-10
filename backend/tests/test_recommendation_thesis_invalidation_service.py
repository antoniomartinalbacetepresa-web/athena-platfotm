from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.recommendation_thesis_invalidation_service import (
    RecommendationThesisCriterionInput,
    RecommendationThesisInvalidationService,
)


AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVAILABLE_AT = AS_OF - timedelta(hours=1)


def _criterion(**overrides: object) -> RecommendationThesisCriterionInput:
    values: dict[str, object] = {
        "name": "gross_margin_floor",
        "metric": "gross_margin",
        "operator": "lt",
        "threshold": 0.35,
        "observed_value": 0.32,
        "available_at": AVAILABLE_AT,
        "source": "sec_filing",
        "source_ref": "filing:example#gross-margin",
    }
    values.update(overrides)
    return RecommendationThesisCriterionInput(**values)  # type: ignore[arg-type]


def test_thesis_invalidation_flags_precommitted_pit_breach_without_sell_advice() -> None:
    result = RecommendationThesisInvalidationService().evaluate(
        symbol=" aapl ",
        as_of=AS_OF,
        criteria=(_criterion(),),
    )

    assert result.symbol == "AAPL"
    assert result.breached_count == 1
    assert result.thesis_invalidation_evidence_present is True
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["automaticProductionPromotion"] is False
    assert payload["policy"]["priceOnlyInvalidation"] == "forbidden"
    assert payload["criteria"][0]["breached"] is True


def test_thesis_invalidation_non_breach_does_not_claim_thesis_is_correct() -> None:
    result = RecommendationThesisInvalidationService().evaluate(
        symbol="AAPL",
        as_of=AS_OF,
        criteria=(_criterion(observed_value=0.40),),
    )

    assert result.breached_count == 0
    assert result.thesis_invalidation_evidence_present is False
    assert "no garantiza" in result.reason


def test_thesis_invalidation_rejects_price_only_rules() -> None:
    service = RecommendationThesisInvalidationService()
    for metric in ("price", "price_drawdown", "total_return", "price_momentum"):
        with pytest.raises(ValueError, match="precio/rentabilidad"):
            service.evaluate(
                symbol="AAPL",
                as_of=AS_OF,
                criteria=(_criterion(metric=metric),),
            )


def test_thesis_invalidation_rejects_lookahead_and_naive_timestamps() -> None:
    service = RecommendationThesisInvalidationService()
    with pytest.raises(ValueError, match="look-ahead"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            criteria=(_criterion(available_at=AS_OF + timedelta(seconds=1)),),
        )
    with pytest.raises(ValueError, match="as_of.*zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=datetime(2026, 1, 1),
            criteria=(_criterion(),),
        )
    with pytest.raises(ValueError, match="criterion.available_at.*zona horaria"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            criteria=(_criterion(available_at=datetime(2025, 12, 31, 23)),),
        )


def test_thesis_invalidation_rejects_non_finite_values_and_missing_provenance() -> None:
    service = RecommendationThesisInvalidationService()
    for field in ("threshold", "observed_value"):
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="finito"):
                service.evaluate(
                    symbol="AAPL",
                    as_of=AS_OF,
                    criteria=(_criterion(**{field: value}),),
                )
    with pytest.raises(ValueError, match="source.*provenance"):
        service.evaluate(symbol="AAPL", as_of=AS_OF, criteria=(_criterion(source=" "),))
    with pytest.raises(ValueError, match="source_ref.*provenance"):
        service.evaluate(symbol="AAPL", as_of=AS_OF, criteria=(_criterion(source_ref=""),))


def test_thesis_invalidation_rejects_duplicate_names_and_invalid_operators() -> None:
    service = RecommendationThesisInvalidationService()
    with pytest.raises(ValueError, match="no pueden repetirse"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            criteria=(_criterion(), _criterion(observed_value=0.31)),
        )
    with pytest.raises(ValueError, match="operator"):
        service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            criteria=(_criterion(operator="eq"),),
        )


def test_thesis_invalidation_supports_all_explicit_comparison_operators() -> None:
    service = RecommendationThesisInvalidationService()
    cases = (
        ("lt", 1.0, 0.9, True),
        ("lte", 1.0, 1.0, True),
        ("gt", 1.0, 1.1, True),
        ("gte", 1.0, 1.0, True),
    )
    for operator, threshold, observed, expected in cases:
        result = service.evaluate(
            symbol="AAPL",
            as_of=AS_OF,
            criteria=(
                _criterion(
                    name=f"rule_{operator}",
                    operator=operator,
                    threshold=threshold,
                    observed_value=observed,
                ),
            ),
        )
        assert result.criteria[0].breached is expected
