from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository
from app.repositories.financial_period_repository import FinancialPeriodRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.services.recommendation_dividend_signal_service import RecommendationDividendSignalService

AS_OF = datetime(2026, 8, 2, tzinfo=timezone.utc)

class _Valuation:
    def __init__(self, *, eps=2.0, unit="USD/share", as_of=AS_OF, entity_id=None): self.eps, self.unit, self.as_of, self.entity_id = eps, unit, as_of, entity_id
    def evaluate(self, *, symbol, as_of):
        payload = {"status":"diagnostic_ready","symbol":symbol,"asOf":self.as_of.isoformat(),"entityId":self.entity_id,"annualDilutedEps":{"value":self.eps,"unit":self.unit},"productionEligible":False}
        return type("ValuationResult", (), {"to_api_dict": lambda self: payload})()

class _Fcf:
    def __init__(self, *, value=4.0, unit="USD", as_of=AS_OF): self.value, self.unit, self.as_of = value, unit, as_of
    def evaluate(self, *, cik, as_of):
        payload={"status":"diagnostic_ready","cik":cik,"asOf":self.as_of.isoformat(),"freeCashFlowPerShare":self.value,"unit":self.unit,"productionEligible":False}
        return type("FcfResult", (), {"to_api_dict": lambda self: payload})()

class _Market:
    def __init__(self, *, status="diagnostic_ready", price=20.0, as_of=AS_OF, return_60d=0.10, price_60d_start=20.0/1.10): self.status,self.price,self.as_of,self.return_60d,self.price_60d_start=status,price,as_of,return_60d,price_60d_start
    def evaluate(self, *, symbol, as_of):
        payload={"status":self.status,"symbol":symbol,"instrumentId":1,"asOf":self.as_of.isoformat(),"latestPrice":self.price,"price60dStart":self.price_60d_start,"latestObservedAt":self.as_of.isoformat(),"latestRetrievedAt":self.as_of.isoformat(),"sourceProviders":["yahoo"],"return60d":self.return_60d,"productionEligible":False}
        return type("MarketResult", (), {"to_api_dict": lambda self: payload})()

def _database(tmp_path: Path) -> AthenaDatabase:
    database=AthenaDatabase(tmp_path/"athena.db"); database.initialize(); return database

def _seed(database: AthenaDatabase) -> int:
    instrument_id=InstrumentRepository(database=database).upsert({"symbol":"DIV","companyName":"Dividend Co","country":"United States","regionKey":"america","exchangeShortName":"NYSE","currency":"USD","instrumentType":"EQUITY","marketCap":1000.0})
    CorporateActionRepository(database=database).save_many(instrument_id=instrument_id,source_provider="primary",retrieved_at=AS_OF,actions=[{"action_type":"dividend","effective_at":datetime(2026,2,1,tzinfo=timezone.utc),"cash_amount":0.5,"currency":"USD"},{"action_type":"dividend","effective_at":datetime(2026,5,1,tzinfo=timezone.utc),"cash_amount":0.5,"currency":"USD"},{"action_type":"dividend","effective_at":datetime(2026,7,15,tzinfo=timezone.utc),"cash_amount":0.25,"currency":"USD"}]); return instrument_id

def test_dividend_signal_uses_same_pit_price_and_cutoff(tmp_path: Path) -> None:
    database=_database(tmp_path); assert _seed(database)==1
    result=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation()).evaluate(symbol="DIV",as_of=AS_OF)
    assert result.status=="diagnostic_ready"; assert result.latest_price==20.0; assert result.price_60d_start==pytest.approx(20.0/1.10); assert result.dividend is not None; assert result.dividend["trailingCashPerShare"]==pytest.approx(1.25); assert result.dividend["trailingYield"]==pytest.approx(0.0625); assert result.dividend["cashPerShare60d"]==pytest.approx(0.25); assert result.dividend["yield60d"]==pytest.approx(0.0125); assert result.price_return_60d==pytest.approx(0.10); assert result.total_return_60d==pytest.approx(0.11375); assert result.earnings_payout_ratio==pytest.approx(0.625); assert result.fcf_payout_ratio is None; assert result.dividend["knowledgeCutoff"]==AS_OF.isoformat(); assert result.production_eligible is False

def test_dividend_signal_fails_closed_without_ready_market_evidence(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); result=RecommendationDividendSignalService(database=database,market_service=_Market(status="insufficient_history")).evaluate(symbol="DIV",as_of=AS_OF); assert result.status=="market_evidence_not_ready"; assert result.dividend is None; assert result.production_eligible is False

def test_dividend_signal_rejects_market_diagnostic_from_different_cutoff(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); service=RecommendationDividendSignalService(database=database,market_service=_Market(as_of=datetime(2026,8,3,tzinfo=timezone.utc)))
    with pytest.raises(RuntimeError,match="otro corte point-in-time"): service.evaluate(symbol="DIV",as_of=AS_OF)

def test_total_return_is_not_fabricated_without_price_return(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); result=RecommendationDividendSignalService(database=database,market_service=_Market(return_60d=None),valuation_service=_Valuation()).evaluate(symbol="DIV",as_of=AS_OF); assert result.dividend is not None; assert result.dividend["trailingYield"]==pytest.approx(0.0625); assert result.price_return_60d is None; assert result.total_return_60d is None

def test_total_return_is_not_fabricated_without_holding_period_start_price(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); result=RecommendationDividendSignalService(database=database,market_service=_Market(price_60d_start=None),valuation_service=_Valuation()).evaluate(symbol="DIV",as_of=AS_OF); assert result.price_return_60d==pytest.approx(0.10); assert result.total_return_60d is None

def test_payout_is_unknown_when_eps_currency_is_not_comparable(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); result=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(unit="EUR/share")).evaluate(symbol="DIV",as_of=AS_OF); assert result.earnings_payout_ratio is None

def test_payout_rejects_valuation_from_different_pit_cutoff(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); service=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(as_of=datetime(2026,8,3,tzinfo=timezone.utc)))
    with pytest.raises(RuntimeError,match="valoración usó otro corte point-in-time"): service.evaluate(symbol="DIV",as_of=AS_OF)

@pytest.mark.parametrize("eps",[0.0,-1.0])
def test_payout_is_unknown_for_nonpositive_eps(tmp_path: Path,eps: float) -> None:
    database=_database(tmp_path); _seed(database); result=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(eps=eps)).evaluate(symbol="DIV",as_of=AS_OF); assert result.earnings_payout_ratio is None

def test_fcf_payout_uses_same_pit_cutoff_currency_and_positive_per_share_fcf(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database)
    result=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(entity_id="sec-cik:0000123456"),free_cash_flow_service=_Fcf(value=4.0)).evaluate(symbol="DIV",as_of=AS_OF)
    assert result.fcf_payout_ratio==pytest.approx(0.3125); assert result.production_eligible is False

@pytest.mark.parametrize("value,unit",[(0.0,"USD"),(-1.0,"USD"),(4.0,"EUR")])
def test_fcf_payout_fails_closed_on_nonpositive_or_currency_mismatch(tmp_path: Path,value: float,unit: str) -> None:
    database=_database(tmp_path); _seed(database)
    result=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(entity_id="sec-cik:0000123456"),free_cash_flow_service=_Fcf(value=value,unit=unit)).evaluate(symbol="DIV",as_of=AS_OF)
    assert result.fcf_payout_ratio is None

def test_fcf_payout_rejects_different_pit_cutoff(tmp_path: Path) -> None:
    database=_database(tmp_path); _seed(database); service=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation(entity_id="sec-cik:0000123456"),free_cash_flow_service=_Fcf(as_of=datetime(2026,8,3,tzinfo=timezone.utc)))
    with pytest.raises(RuntimeError,match="FCF devolvió un contrato PIT inválido"): service.evaluate(symbol="DIV",as_of=AS_OF)


def test_dividend_signal_binds_explicit_repository_backed_sustainability_without_auto_authority(tmp_path: Path) -> None:
    database=_database(tmp_path); instrument_id=_seed(database)
    FinancialPeriodRepository(database).save_many(
        instrument_id=instrument_id,
        source_provider="issuer_filing",
        retrieved_at=AS_OF,
        periods=[{
            "period_start": datetime(2025,1,1,tzinfo=timezone.utc),
            "period_end": datetime(2025,12,31,tzinfo=timezone.utc),
            "currency": "USD",
            "net_income": 100.0,
            "free_cash_flow": 80.0,
            "dividends_paid": 40.0,
            "source_timestamp": AS_OF,
        }],
    )
    service=RecommendationDividendSignalService(database=database,market_service=_Market(),valuation_service=_Valuation())
    without_authority=service.evaluate(symbol="DIV",as_of=AS_OF)
    assert without_authority.financial_period_sustainability is None
    assert without_authority.earnings_payout_ratio==pytest.approx(0.625)
    assert without_authority.fcf_payout_ratio is None
    result=service.evaluate(symbol="DIV",as_of=AS_OF,sustainability_provider="issuer_filing")
    assert result.financial_period_sustainability is not None
    assert result.financial_period_sustainability["earningsPayoutRatio"]==pytest.approx(0.40)
    assert result.financial_period_sustainability["fcfPayoutRatio"]==pytest.approx(0.50)
    assert result.financial_period_sustainability["sustainabilityScore"]==pytest.approx(0.55)
    assert result.financial_period_sustainability["sourceProvider"]=="issuer_filing"
    assert result.financial_period_sustainability["knowledgeCutoff"]==AS_OF.isoformat()
    assert result.earnings_payout_ratio==pytest.approx(0.40)
    assert result.fcf_payout_ratio==pytest.approx(0.50)
    assert result.production_eligible is False
