from datetime import datetime, timezone
import math

import pytest

from app.services.recommendation_portfolio_time_weighted_return_service import (
    PortfolioCashFlowEvidence,
    PortfolioTwrSegment,
    PortfolioValueEvidence,
    RecommendationPortfolioTimeWeightedReturnInput,
    RecommendationPortfolioTimeWeightedReturnService,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW_AT = datetime(2026, 1, 16, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
AS_OF = datetime(2026, 2, 2, tzinfo=UTC)


def value(amount: float, observed_at: datetime, ref: str) -> PortfolioValueEvidence:
    return PortfolioValueEvidence(
        value=amount,
        observed_at=observed_at,
        available_at=observed_at,
        source="portfolio_ledger",
        source_ref=ref,
    )


def flow(amount: float, occurred_at: datetime, ref: str) -> PortfolioCashFlowEvidence:
    return PortfolioCashFlowEvidence(
        amount=amount,
        occurred_at=occurred_at,
        available_at=occurred_at,
        source="broker_statement",
        source_ref=ref,
    )


def item(*, second_beginning: float = 121.0) -> RecommendationPortfolioTimeWeightedReturnInput:
    return RecommendationPortfolioTimeWeightedReturnInput(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        segments=(
            PortfolioTwrSegment(
                start_at=START,
                end_at=FLOW_AT,
                beginning_value=value(100.0, START, "v-start"),
                ending_value_before_flow=value(110.0, FLOW_AT, "v-pre-flow"),
                external_flow_after_end=flow(11.0, FLOW_AT, "deposit-1"),
            ),
            PortfolioTwrSegment(
                start_at=FLOW_AT,
                end_at=END,
                beginning_value=value(second_beginning, FLOW_AT, "v-post-flow"),
                ending_value_before_flow=value(133.1, END, "v-end"),
            ),
        ),
    )


def test_twr_reconciles_external_flow_and_geometrically_chains_returns() -> None:
    result = RecommendationPortfolioTimeWeightedReturnService().evaluate(as_of=AS_OF, item=item())

    assert result.external_flow_count == 1
    assert result.net_external_flow == 11.0
    assert math.isclose(result.segment_returns[0]["segmentReturn"], 0.10, abs_tol=1e-12)
    assert math.isclose(result.segment_returns[1]["segmentReturn"], 0.10, abs_tol=1e-12)
    assert math.isclose(result.time_weighted_return, 0.21, abs_tol=1e-12)
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["policy"]["cashInference"] == "forbidden"
    assert len(result.return_key) == 64


def test_twr_fails_closed_when_post_flow_value_does_not_reconcile() -> None:
    with pytest.raises(ValueError, match="post-flow beginning value"):
        RecommendationPortfolioTimeWeightedReturnService().evaluate(
            as_of=AS_OF,
            item=item(second_beginning=120.0),
        )


def test_twr_rejects_late_knowledge() -> None:
    late = PortfolioTwrSegment(
        start_at=START,
        end_at=END,
        beginning_value=PortfolioValueEvidence(
            value=100.0,
            observed_at=START,
            available_at=AS_OF.replace(day=3),
            source="ledger",
            source_ref="late",
        ),
        ending_value_before_flow=value(110.0, END, "end"),
    )
    with pytest.raises(ValueError, match="observed_at <= available_at <= as_of"):
        RecommendationPortfolioTimeWeightedReturnService().evaluate(
            as_of=AS_OF,
            item=RecommendationPortfolioTimeWeightedReturnInput(
                portfolio_id="p",
                reporting_currency="USD",
                period_start=START,
                period_end=END,
                segments=(late,),
            ),
        )


def test_twr_rejects_nonfinite_values() -> None:
    bad = PortfolioTwrSegment(
        start_at=START,
        end_at=END,
        beginning_value=value(float("nan"), START, "nan"),
        ending_value_before_flow=value(110.0, END, "end"),
    )
    with pytest.raises(ValueError, match="finite"):
        RecommendationPortfolioTimeWeightedReturnService().evaluate(
            as_of=AS_OF,
            item=RecommendationPortfolioTimeWeightedReturnInput(
                portfolio_id="p",
                reporting_currency="USD",
                period_start=START,
                period_end=END,
                segments=(bad,),
            ),
        )


def test_twr_rejects_flow_after_final_period_boundary() -> None:
    segment = PortfolioTwrSegment(
        start_at=START,
        end_at=END,
        beginning_value=value(100.0, START, "start"),
        ending_value_before_flow=value(110.0, END, "end"),
        external_flow_after_end=flow(10.0, END, "outside"),
    )
    with pytest.raises(ValueError, match="outside the measurement period"):
        RecommendationPortfolioTimeWeightedReturnService().evaluate(
            as_of=AS_OF,
            item=RecommendationPortfolioTimeWeightedReturnInput(
                portfolio_id="p",
                reporting_currency="USD",
                period_start=START,
                period_end=END,
                segments=(segment,),
            ),
        )


def test_twr_identity_is_deterministic_and_provenance_bound() -> None:
    service = RecommendationPortfolioTimeWeightedReturnService()
    first = service.evaluate(as_of=AS_OF, item=item()).return_key
    second = service.evaluate(as_of=AS_OF, item=item()).return_key
    changed = RecommendationPortfolioTimeWeightedReturnInput(
        **{
            **item().__dict__,
            "segments": (
                PortfolioTwrSegment(
                    start_at=START,
                    end_at=FLOW_AT,
                    beginning_value=value(100.0, START, "different-source-ref"),
                    ending_value_before_flow=value(110.0, FLOW_AT, "v-pre-flow"),
                    external_flow_after_end=flow(11.0, FLOW_AT, "deposit-1"),
                ),
                item().segments[1],
            ),
        }
    )
    third = service.evaluate(as_of=AS_OF, item=changed).return_key
    assert first == second
    assert first != third
