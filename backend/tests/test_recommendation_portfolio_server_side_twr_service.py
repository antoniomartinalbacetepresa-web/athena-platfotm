from datetime import datetime, timezone

import pytest

from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput,
    RecommendationPortfolioEventLedgerService,
)
from app.services.recommendation_portfolio_server_side_twr_service import (
    RecommendationPortfolioServerSideTwrService,
)
from app.services.recommendation_portfolio_twr_measurement_service import PortfolioTwrBoundaryInput


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW = datetime(2026, 1, 10, tzinfo=UTC)
INTERNAL = datetime(2026, 1, 15, tzinfo=UTC)
END = datetime(2026, 1, 20, tzinfo=UTC)
AS_OF = datetime(2026, 1, 21, tzinfo=UTC)
SCOPE = "total_net_liquidation_value_in_reporting_currency"


def _boundary(observed_at, *, pre, post, flow=0.0, fingerprint):
    return PortfolioTwrBoundaryInput(
        observed_at=observed_at,
        available_at=observed_at,
        pre_flow_value=pre,
        post_flow_value=post,
        external_flow_amount=flow,
        currency="EUR",
        valuation_scope=SCOPE,
        valuation_fingerprint=fingerprint,
        source="broker_net_liquidation_statement",
        source_ref=f"nlv:{observed_at.isoformat()}",
    )


def _boundaries():
    return (
        _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64),
        _boundary(FLOW, pre=110.0, post=160.0, flow=50.0, fingerprint="2" * 64),
        _boundary(END, pre=176.0, post=176.0, fingerprint="3" * 64),
    )


def _append(ledger, *, event_type, when, amount, instrument_id=None, source_ref):
    return ledger.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type=event_type,
            occurred_at=when,
            available_at=when,
            currency="EUR",
            amount=amount,
            instrument_id=instrument_id,
            quantity=None,
            source="broker_statement",
            source_ref=source_ref,
        ),
    )


def test_server_side_twr_reads_external_and_internal_events_from_same_canonical_ledger(tmp_path):
    path = tmp_path / "portfolio-ledger.jsonl"
    ledger = RecommendationPortfolioEventLedgerService(path)
    _append(ledger, event_type="external_cash_flow", when=FLOW, amount=50.0, source_ref="deposit-1")
    dividend = _append(
        ledger,
        event_type="cash_dividend",
        when=INTERNAL,
        amount=2.0,
        instrument_id="instrument-1",
        source_ref="dividend-1",
    )
    _append(ledger, event_type="fee", when=INTERNAL, amount=-0.5, source_ref="fee-1")
    _append(ledger, event_type="tax", when=INTERNAL, amount=-0.25, source_ref="tax-1")

    result = RecommendationPortfolioServerSideTwrService(ledger_path=path).evaluate(
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
        boundaries=_boundaries(),
    )

    assert result.core.core.time_weighted_return == pytest.approx(0.21)
    payload = result.to_api_dict()
    assert payload["status"] == "measured_from_canonical_server_side_portfolio_ledger"
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["callerSuppliedExternalCashFlowLedger"] is False
    assert payload["policy"]["callerSuppliedInternalCashEvents"] is False
    assert payload["serverSideLedger"]["externalEventCount"] == 1
    assert payload["serverSideLedger"]["internalEventCount"] == 3
    assert payload["serverSideLedger"]["ledgerHeadHash"] == ledger.load()[-1].record_hash
    assert payload["internalCashTotals"] == {
        "cash_dividend": pytest.approx(2.0),
        "fee": pytest.approx(-0.5),
        "tax": pytest.approx(-0.25),
    }
    assert any(item["eventKey"] == dividend.event.event_key for item in payload["internalCashEvents"])


def test_server_side_twr_rejects_omitted_or_invented_external_flow_boundaries(tmp_path):
    path = tmp_path / "portfolio-ledger.jsonl"
    ledger = RecommendationPortfolioEventLedgerService(path)
    _append(ledger, event_type="external_cash_flow", when=FLOW, amount=50.0, source_ref="deposit-1")
    service = RecommendationPortfolioServerSideTwrService(ledger_path=path)

    omitted = (
        _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64),
        _boundary(END, pre=176.0, post=176.0, fingerprint="3" * 64),
    )
    with pytest.raises(ValueError, match="known ledger external cash flow is missing an exact TWR valuation boundary"):
        service.evaluate(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=omitted,
        )

    empty_path = tmp_path / "empty-ledger.jsonl"
    with pytest.raises(ValueError, match="absent from the supplied ledger evidence"):
        RecommendationPortfolioServerSideTwrService(ledger_path=empty_path).evaluate(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=_boundaries(),
        )


def test_server_side_twr_fails_closed_on_fx_and_tampered_ledger(tmp_path):
    path = tmp_path / "portfolio-ledger.jsonl"
    ledger = RecommendationPortfolioEventLedgerService(path)
    ledger.append(
        as_of=AS_OF,
        item=PortfolioLedgerEventInput(
            portfolio_id="portfolio-1",
            event_type="external_cash_flow",
            occurred_at=FLOW,
            available_at=FLOW,
            currency="USD",
            amount=50.0,
            instrument_id=None,
            quantity=None,
            source="broker_statement",
            source_ref="usd-deposit",
        ),
    )
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        RecommendationPortfolioServerSideTwrService(ledger_path=path).evaluate(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=_boundaries(),
        )

    clean = tmp_path / "tampered.jsonl"
    ledger = RecommendationPortfolioEventLedgerService(clean)
    _append(ledger, event_type="external_cash_flow", when=FLOW, amount=50.0, source_ref="deposit-1")
    raw = clean.read_text(encoding="utf-8")
    clean.write_text(raw.replace('"amount":50.0', '"amount":5000.0'), encoding="utf-8")
    with pytest.raises(ValueError, match="record hash is invalid"):
        RecommendationPortfolioServerSideTwrService(ledger_path=clean).evaluate(
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=_boundaries(),
        )
