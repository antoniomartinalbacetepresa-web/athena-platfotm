from datetime import datetime, timezone

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.recommendation_portfolio_event_journal_repository import (
    RecommendationPortfolioEventJournalRepository,
)
from app.services.recommendation_portfolio_persisted_twr_service import (
    RecommendationPortfolioPersistedTwrService,
)
from app.services.recommendation_portfolio_twr_measurement_service import (
    PortfolioTwrBoundaryInput,
)


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW = datetime(2026, 1, 10, tzinfo=UTC)
END = datetime(2026, 1, 20, tzinfo=UTC)
AS_OF = datetime(2026, 1, 21, tzinfo=UTC)
SCOPE = "total_net_liquidation_value_in_reporting_currency"


def _repo(tmp_path):
    return RecommendationPortfolioEventJournalRepository(
        AthenaDatabase(tmp_path / "athena.db")
    )


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
        source_ref=f"valuation:{observed_at.isoformat()}",
    )


def _boundaries():
    return (
        _boundary(START, pre=100.0, post=100.0, fingerprint="1" * 64),
        _boundary(FLOW, pre=110.0, post=160.0, flow=50.0, fingerprint="2" * 64),
        _boundary(END, pre=176.0, post=176.0, fingerprint="3" * 64),
    )


def _append(repository, *, key="a" * 64, amount=50.0, source_ref="deposit-1"):
    return repository.append_external_cash_flow(
        tenant_id="tenant-1",
        portfolio_id="portfolio-1",
        event_key=key,
        amount=amount,
        currency="EUR",
        occurred_at=FLOW,
        available_at=FLOW,
        source="broker_statement",
        source_ref=source_ref,
    )


def test_server_side_journal_is_idempotent_hash_chained_and_tenant_scoped(tmp_path):
    repository = _repo(tmp_path)
    first = _append(repository)
    second = _append(repository)

    assert second == first
    assert first["previous_record_fingerprint"] is None
    assert len(first["record_fingerprint"]) == 64

    other = repository.scan_external_cash_flows(
        tenant_id="tenant-2",
        portfolio_id="portfolio-1",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
    )
    assert other == ()


def test_persisted_twr_reads_flows_from_journal_and_preserves_safety(tmp_path):
    repository = _repo(tmp_path)
    _append(repository)
    result = RecommendationPortfolioPersistedTwrService(
        journal_repository=repository
    ).evaluate(
        tenant_id="tenant-1",
        portfolio_id="portfolio-1",
        reporting_currency="EUR",
        period_start=START,
        period_end=END,
        as_of=AS_OF,
        boundaries=_boundaries(),
    )

    assert result.core.core.time_weighted_return == pytest.approx(0.21)
    payload = result.to_api_dict()
    assert payload["advisoryStatus"] == "no_advice"
    assert payload["productionEligible"] is False
    assert payload["isWeightingReady"] is False
    assert payload["policy"]["callerSuppliedExternalCashFlowLedger"] is False
    assert payload["policy"]["automaticTrading"] is False
    assert payload["persistedLedger"]["serverSide"] is True
    assert payload["persistedLedger"]["tamperEvidentHashChain"] is True
    assert payload["persistedLedger"]["selectedEventCount"] == 1


def test_tampering_and_head_truncation_are_detected_before_twr(tmp_path):
    repository = _repo(tmp_path)
    record = _append(repository)

    with repository._database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_portfolio_event_journal
            SET amount = 5000.0
            WHERE id = ?
            """,
            (record["id"],),
        )

    with pytest.raises(ValueError, match="modified"):
        repository.scan_external_cash_flows(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )

    repository = _repo(tmp_path / "second")
    _append(repository)
    with repository._database.connect() as connection:
        connection.execute(
            """
            UPDATE athena_recommendation_portfolio_event_journal_head
            SET event_count = 0
            WHERE tenant_id = 'tenant-1' AND portfolio_id = 'portfolio-1'
            """
        )
    with pytest.raises(ValueError, match="event count"):
        repository.scan_external_cash_flows(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
        )


def test_collision_nonfinite_fx_and_lookahead_fail_closed(tmp_path):
    repository = _repo(tmp_path)
    _append(repository)

    with pytest.raises(ValueError, match="collision"):
        repository.append_external_cash_flow(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            event_key="a" * 64,
            amount=51.0,
            currency="EUR",
            occurred_at=FLOW,
            available_at=FLOW,
            source="broker_statement",
            source_ref="deposit-1-changed",
        )

    with pytest.raises(ValueError, match="finite"):
        repository.append_external_cash_flow(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            event_key="b" * 64,
            amount=float("nan"),
            currency="EUR",
            occurred_at=FLOW,
            available_at=FLOW,
            source="broker_statement",
            source_ref="nan",
        )

    usd_repo = _repo(tmp_path / "usd")
    usd_repo.append_external_cash_flow(
        tenant_id="tenant-1",
        portfolio_id="portfolio-1",
        event_key="c" * 64,
        amount=50.0,
        currency="USD",
        occurred_at=FLOW,
        available_at=FLOW,
        source="broker_statement",
        source_ref="usd",
    )
    service = RecommendationPortfolioPersistedTwrService(
        journal_repository=usd_repo
    )
    with pytest.raises(ValueError, match="explicit FX conversion evidence"):
        service.evaluate(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=_boundaries(),
        )

    future_repo = _repo(tmp_path / "future")
    future_repo.append_external_cash_flow(
        tenant_id="tenant-1",
        portfolio_id="portfolio-1",
        event_key="d" * 64,
        amount=50.0,
        currency="EUR",
        occurred_at=FLOW,
        available_at=datetime(2026, 1, 22, tzinfo=UTC),
        source="broker_statement",
        source_ref="future",
    )
    with pytest.raises(ValueError, match="absent from the supplied ledger evidence"):
        RecommendationPortfolioPersistedTwrService(
            journal_repository=future_repo
        ).evaluate(
            tenant_id="tenant-1",
            portfolio_id="portfolio-1",
            reporting_currency="EUR",
            period_start=START,
            period_end=END,
            as_of=AS_OF,
            boundaries=_boundaries(),
        )
