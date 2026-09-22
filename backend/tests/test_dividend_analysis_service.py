from datetime import datetime, timezone
from pathlib import Path
import pytest
from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.dividend_analysis_service import DividendAnalysisService


def _database(tmp_path: Path) -> AthenaDatabase:
    database=AthenaDatabase(tmp_path/"athena.db"); database.initialize(); return database

def _instrument(database:AthenaDatabase)->int:
    return InstrumentRepository(database=database).upsert({"symbol":"DIV","companyName":"Dividend Co","country":"United States","regionKey":"america","exchangeShortName":"NYSE","currency":"USD","instrumentType":"EQUITY","marketCap":1000.0})

def _save(database,instrument_id,provider,retrieved_at,dates):
    CorporateActionRepository(database=database).save_many(instrument_id=instrument_id,source_provider=provider,retrieved_at=retrieved_at,actions=[{"action_type":"dividend","effective_at":d,"cash_amount":0.25,"currency":"USD"} for d in dates])

def test_quarterly_dividends_are_classified_and_duplicate_providers_count_once(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); known=datetime(2026,8,2,tzinfo=timezone.utc); dates=[datetime(2025,8,1,tzinfo=timezone.utc),datetime(2025,11,1,tzinfo=timezone.utc),datetime(2026,2,1,tzinfo=timezone.utc),datetime(2026,5,1,tzinfo=timezone.utc),datetime(2026,8,1,tzinfo=timezone.utc)]; _save(db,iid,"primary",known,dates); _save(db,iid,"secondary",known,dates); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=known,pit_price=20.0); assert r.payment_count==5 and r.frequency=="quarterly" and r.trailing_yield==pytest.approx(.05) and r.regularity_score>.95

def test_growth_cut_and_no_cut_years_are_pit_bounded(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); repo=CorporateActionRepository(database=db); known=datetime(2026,8,2,tzinfo=timezone.utc); actions=[]
    for d in [datetime(2024,11,1,tzinfo=timezone.utc),datetime(2025,2,1,tzinfo=timezone.utc),datetime(2025,5,1,tzinfo=timezone.utc)]: actions.append({"action_type":"dividend","effective_at":d,"cash_amount":.5,"currency":"USD"})
    for d in [datetime(2025,11,1,tzinfo=timezone.utc),datetime(2026,2,1,tzinfo=timezone.utc),datetime(2026,5,1,tzinfo=timezone.utc)]: actions.append({"action_type":"dividend","effective_at":d,"cash_amount":.4,"currency":"USD"})
    repo.save_many(instrument_id=iid,source_provider="primary",retrieved_at=known,actions=actions); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=known); assert r.dividend_growth_rate==pytest.approx(-.2) and r.cut_detected is True and r.consecutive_full_years_without_cut==0

def test_sparse_history_keeps_growth_unknown(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); known=datetime(2026,8,2,tzinfo=timezone.utc); _save(db,iid,"primary",known,[datetime(2026,2,1,tzinfo=timezone.utc),datetime(2026,5,1,tzinfo=timezone.utc)]); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=known); assert r.dividend_growth_rate is None and r.cut_detected is None and r.consecutive_full_years_without_cut is None

def test_suspension_requires_established_regular_cadence(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); cutoff=datetime(2026,8,2,tzinfo=timezone.utc); _save(db,iid,"primary",cutoff,[datetime(2025,5,1,tzinfo=timezone.utc),datetime(2025,8,1,tzinfo=timezone.utc),datetime(2025,11,1,tzinfo=timezone.utc),datetime(2026,2,1,tzinfo=timezone.utc)]); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=cutoff); assert r.frequency=="quarterly" and r.suspected_suspension is True and r.payment_stability_score==0.0

def test_irregular_history_does_not_invent_suspension(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); cutoff=datetime(2026,8,2,tzinfo=timezone.utc); _save(db,iid,"primary",cutoff,[datetime(2025,12,1,tzinfo=timezone.utc),datetime(2025,12,21,tzinfo=timezone.utc),datetime(2026,3,11,tzinfo=timezone.utc)]); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=cutoff); assert r.frequency=="irregular" and r.suspected_suspension is None

def test_confirmed_forward_dividend_is_separate_from_paid_and_has_provenance(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); repo=CorporateActionRepository(database=db); cutoff=datetime(2026,6,1,tzinfo=timezone.utc); known=datetime(2026,5,20,tzinfo=timezone.utc)
    repo.save_many(instrument_id=iid,source_provider="exchange_notice",retrieved_at=known,actions=[{"action_type":"dividend","effective_at":datetime(2026,7,1,tzinfo=timezone.utc),"cash_amount":.30,"currency":"USD"}])
    r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=cutoff,pit_price=20.0); assert r.payment_count==0 and r.trailing_yield is None; assert r.confirmed_forward_payment_count==1 and r.confirmed_forward_cash_per_share==pytest.approx(.30) and r.confirmed_forward_yield==pytest.approx(.015); assert r.confirmed_forward_source_providers==("exchange_notice",) and r.confirmed_forward_latest_retrieved_at==known.isoformat()

def test_forward_dividend_discovered_after_cutoff_cannot_leak(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); repo=CorporateActionRepository(database=db); cutoff=datetime(2026,6,1,tzinfo=timezone.utc); repo.save_many(instrument_id=iid,source_provider="exchange_notice",retrieved_at=datetime(2026,6,2,tzinfo=timezone.utc),actions=[{"action_type":"dividend","effective_at":datetime(2026,7,1,tzinfo=timezone.utc),"cash_amount":.30,"currency":"USD"}]); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=cutoff,pit_price=20.0); assert r.confirmed_forward_payment_count==0 and r.confirmed_forward_cash_per_share is None and r.confirmed_forward_yield is None

def test_mixed_currency_forward_cash_fails_closed(tmp_path):
    db=_database(tmp_path); iid=_instrument(db); repo=CorporateActionRepository(database=db); cutoff=datetime(2026,6,1,tzinfo=timezone.utc); known=datetime(2026,5,20,tzinfo=timezone.utc); repo.save_many(instrument_id=iid,source_provider="notice",retrieved_at=known,actions=[{"action_type":"dividend","effective_at":datetime(2026,7,1,tzinfo=timezone.utc),"cash_amount":.3,"currency":"USD"},{"action_type":"dividend","effective_at":datetime(2026,8,1,tzinfo=timezone.utc),"cash_amount":.2,"currency":"EUR"}]); r=DividendAnalysisService(database=db).analyze(instrument_id=iid,knowledge_cutoff=cutoff,pit_price=20.0); assert r.confirmed_forward_payment_count==2 and r.confirmed_forward_cash_per_share is None and r.confirmed_forward_yield is None
