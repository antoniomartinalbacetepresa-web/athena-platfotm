"""Ledger provenance and amount validation, including historical replay."""
from dataclasses import replace
from datetime import datetime, timezone
import json
import pytest
from app.services.recommendation_portfolio_event_ledger_service import (
    PortfolioLedgerEventInput, PortfolioLedgerRecord, RecommendationPortfolioEventLedgerService,
)
AT = datetime(2026, 1, 16, tzinfo=timezone.utc)
AS_OF = datetime(2026, 2, 2, tzinfo=timezone.utc)

def _flow(**changes):
    values = dict(portfolio_id="owner-1", event_type="external_cash_flow",
                  occurred_at=AT, available_at=AT, currency="EUR", amount=11.0,
                  instrument_id=None, quantity=None,
                  source="broker_statement", source_ref="deposit-1")
    values.update(changes)
    return PortfolioLedgerEventInput(**values)

@pytest.mark.parametrize("field", ("source", "source_ref"))
@pytest.mark.parametrize("alias", ("FMP", "Financial Modeling Prep", "ＦＭＰ", "f-m-p",
    "&#70;&#77;&#80;", "&amp;#70;&amp;#77;&amp;#80;", "%46%4d%50",
    "%26%2370%3B%26%2377%3B%26%2380%3B", "f&#x200b;mp"))
def test_reject_fmp_without_writing(tmp_path, field, alias):
    path = tmp_path / "ledger.jsonl"
    with pytest.raises(ValueError, match="FMP"):
        RecommendationPortfolioEventLedgerService(path).append(
            as_of=AS_OF, item=_flow(**{field: alias}))
    assert not path.exists()

@pytest.mark.parametrize("field", ("source", "source_ref"))
@pytest.mark.parametrize("bad", (None, "", "  ", 123))
def test_provenance_must_be_string(tmp_path, field, bad):
    with pytest.raises(ValueError, match="required"):
        RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl").append(
            as_of=AS_OF, item=_flow(**{field: bad}))

@pytest.mark.parametrize("bad", (True, False, "11", b"11", float("nan"), float("inf")))
def test_reject_coerced_or_nonfinite_cash(tmp_path, bad):
    with pytest.raises(ValueError, match="finite"):
        RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl").append(
            as_of=AS_OF, item=_flow(amount=bad))

def test_historical_encoded_provenance_fails_closed(tmp_path):
    path = tmp_path / "ledger.jsonl"
    svc = RecommendationPortfolioEventLedgerService(path)
    original = svc.normalize(as_of=AS_OF, item=_flow())
    legacy = replace(original, source_ref="&#70;MP")
    record = PortfolioLedgerRecord(1, svc.GENESIS_HASH,
        svc._record_hash(1, svc.GENESIS_HASH, legacy), legacy)
    path.write_text(json.dumps(record.to_dict()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed") as exc:
        svc.load()
    assert isinstance(exc.value.__cause__, ValueError)
    assert "FMP" in str(exc.value.__cause__)

def test_legitimate_idempotent_and_no_trading(tmp_path):
    svc = RecommendationPortfolioEventLedgerService(tmp_path / "ledger.jsonl")
    first = svc.append(as_of=AS_OF, item=_flow())
    assert first == svc.append(as_of=AS_OF, item=_flow())
    assert len(svc.load()) == 1
    assert svc.policy()["automaticTrading"] is False
    assert svc.policy()["productionEligible"] is False
