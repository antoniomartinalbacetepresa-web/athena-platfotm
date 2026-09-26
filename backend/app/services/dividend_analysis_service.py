from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from app.database.athena_database import AthenaDatabase
from app.repositories.corporate_action_repository import CorporateActionRepository


@dataclass(frozen=True)
class DividendAnalysis:
    payment_count: int
    annualized_cash_per_share: float | None
    trailing_cash_per_share: float
    trailing_yield: float | None
    cash_per_share_60d: float | None
    yield_60d: float | None
    frequency: str
    payments_per_year: float | None
    regularity_score: float | None
    dividend_growth_rate: float | None
    cut_detected: bool | None
    consecutive_full_years_without_cut: int | None
    payment_stability_score: float | None
    suspected_suspension: bool | None
    currency: str | None
    currency_consistent: bool
    knowledge_cutoff: str
    confirmed_forward_payment_count: int = 0
    confirmed_forward_cash_per_share: float | None = None
    confirmed_forward_yield: float | None = None
    confirmed_forward_source_providers: tuple[str, ...] = ()
    confirmed_forward_latest_retrieved_at: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "paymentCount": self.payment_count, "annualizedCashPerShare": self.annualized_cash_per_share,
            "trailingCashPerShare": self.trailing_cash_per_share, "trailingYield": self.trailing_yield,
            "cashPerShare60d": self.cash_per_share_60d, "yield60d": self.yield_60d, "frequency": self.frequency,
            "paymentsPerYear": self.payments_per_year, "regularityScore": self.regularity_score,
            "dividendGrowthRate": self.dividend_growth_rate, "cutDetected": self.cut_detected,
            "consecutiveFullYearsWithoutCut": self.consecutive_full_years_without_cut,
            "paymentStabilityScore": self.payment_stability_score, "suspectedSuspension": self.suspected_suspension,
            "currency": self.currency, "currencyConsistent": self.currency_consistent,
            "knowledgeCutoff": self.knowledge_cutoff, "pitSafe": True,
            "confirmedForwardPaymentCount": self.confirmed_forward_payment_count,
            "confirmedForwardCashPerShare": self.confirmed_forward_cash_per_share,
            "confirmedForwardYield": self.confirmed_forward_yield,
            "confirmedForwardSourceProviders": list(self.confirmed_forward_source_providers),
            "confirmedForwardLatestRetrievedAt": self.confirmed_forward_latest_retrieved_at,
        }


class DividendAnalysisService:
    """PIT-safe dividend cadence, growth and cash-distribution diagnostics.

    Confirmed-forward fields contain only future-effective dividend actions already
    retrieved by the knowledge cutoff, never cadence projections or estimates.
    """
    _MIN_SUSPENSION_INTERVALS = 3
    _MIN_SUSPENSION_REGULARITY = 0.80
    _SUSPENSION_OVERDUE_MULTIPLIER = 1.75

    def __init__(self, *, database: AthenaDatabase | None = None) -> None:
        self._database = database if database is not None else AthenaDatabase()
        self._repository = CorporateActionRepository(database=self._database)

    def analyze(self, *, instrument_id: int, knowledge_cutoff: datetime, lookback_days: int = 730, pit_price: float | None = None) -> DividendAnalysis:
        if instrument_id <= 0: raise ValueError("instrument_id debe ser positivo.")
        if knowledge_cutoff.tzinfo is None or knowledge_cutoff.utcoffset() is None: raise ValueError("knowledge_cutoff debe incluir zona horaria.")
        if lookback_days < 365: raise ValueError("lookback_days debe ser al menos 365 para inferir frecuencia.")
        if pit_price is not None and pit_price <= 0: raise ValueError("pit_price debe ser positivo cuando se proporciona.")
        cutoff = knowledge_cutoff.astimezone(timezone.utc)
        actions = self._repository.list_for_instrument(instrument_id, knowledge_cutoff=cutoff)
        dividends = [row for row in actions if row["action_type"] == "dividend"]
        unique: dict[tuple[str, float, str | None], dict[str, Any]] = {}
        for row in dividends:
            effective = datetime.fromisoformat(str(row["effective_at"])); age = (cutoff-effective).total_seconds()/86400.0
            if 0 <= age <= lookback_days: unique.setdefault((str(row["effective_at"]),float(row["cash_amount"]),row["currency"]),row)
        ordered=sorted(unique.values(),key=lambda row:str(row["effective_at"]))
        currencies={row["currency"] for row in ordered if row["currency"] is not None}
        currency_consistent=len(currencies)<=1 and all(row["currency"] is not None for row in ordered)
        currency=next(iter(currencies)) if currency_consistent and currencies else None

        # Forward horizon is explicitly one year and contains only actions known PIT.
        future_rows=[r for r in self._repository.list_known_future_for_instrument(instrument_id,knowledge_cutoff=cutoff,effective_to=cutoff+timedelta(days=365)) if r["action_type"]=="dividend"]
        future_unique={(str(r["effective_at"]),float(r["cash_amount"]),r["currency"]):r for r in future_rows}
        future=list(future_unique.values()); future_currencies={r["currency"] for r in future if r["currency"] is not None}
        forward_currency_ok=bool(future) and len(future_currencies)==1 and all(r["currency"] is not None for r in future)
        if currency is not None and forward_currency_ok: forward_currency_ok=next(iter(future_currencies))==currency
        forward_cash=sum(float(r["cash_amount"]) for r in future) if forward_currency_ok else None
        forward_yield=forward_cash/pit_price if forward_cash is not None and pit_price is not None else None
        forward_providers=tuple(sorted({str(r["source_provider"]) for r in future}))
        forward_latest=max((str(r["retrieved_at"]) for r in future),default=None)

        def build(*args: Any) -> DividendAnalysis:
            return DividendAnalysis(*args, confirmed_forward_payment_count=len(future), confirmed_forward_cash_per_share=forward_cash,
                confirmed_forward_yield=forward_yield, confirmed_forward_source_providers=forward_providers,
                confirmed_forward_latest_retrieved_at=forward_latest)
        if not ordered: return build(0,None,0.0,None,None,None,"none",None,None,None,None,None,None,None,None,True,cutoff.isoformat())
        def age_days(row:dict[str,Any])->float: return (cutoff-datetime.fromisoformat(str(row["effective_at"]))).total_seconds()/86400.0
        annual_windows=[]
        for i in range(max(1,lookback_days//365)):
            lower=i*365; upper=(i+1)*365
            annual_windows.append([r for r in ordered if lower<age_days(r)<=upper or (i==0 and age_days(r)==0)])
        trailing=annual_windows[0]; prior=annual_windows[1] if len(annual_windows)>1 else []
        trailing_cash=sum(float(r["cash_amount"]) for r in trailing) if currency_consistent else 0.0; prior_cash=sum(float(r["cash_amount"]) for r in prior) if currency_consistent else 0.0
        trailing_yield=trailing_cash/pit_price if currency_consistent and trailing and pit_price is not None else None
        rows60=[r for r in ordered if 0<=age_days(r)<=60]; cash60=sum(float(r["cash_amount"]) for r in rows60) if currency_consistent and rows60 else None; yield60=cash60/pit_price if cash60 is not None and pit_price is not None else None
        growth=cut=years=None
        if currency_consistent and trailing and prior and prior_cash>0:
            growth=trailing_cash/prior_cash-1.0; cut=growth < -1e-12; years=0; newer=trailing_cash
            for older in annual_windows[1:]:
                if not older: break
                old=sum(float(r["cash_amount"]) for r in older)
                if old<=0 or newer<old-1e-12: break
                years+=1; newer=old
        if len(ordered)<2: return build(len(ordered),None,trailing_cash,trailing_yield,cash60,yield60,"insufficient_history",None,None,growth,cut,years,None,None,currency,currency_consistent,cutoff.isoformat())
        dates=[datetime.fromisoformat(str(r["effective_at"])) for r in ordered]; intervals=[(b-a).total_seconds()/86400.0 for a,b in zip(dates,dates[1:])]; typical=median(intervals)
        frequency,expected=self._classify_frequency(typical); ppy=365.2425/typical if typical>0 else None; regularity=None
        if expected is not None: regularity=max(0.0,min(1.0,1.0-sum(abs(d-expected)/expected for d in intervals)/len(intervals)))
        established=expected is not None and len(intervals)>=self._MIN_SUSPENSION_INTERVALS and regularity is not None and regularity>=self._MIN_SUSPENSION_REGULARITY
        stability=regularity if established else None; suspension=None
        if established and expected is not None:
            suspension=age_days(ordered[-1])>expected*self._SUSPENSION_OVERDUE_MULTIPLIER
            if suspension: stability=0.0
        annualized=trailing_cash if currency_consistent and trailing else None
        return build(len(ordered),annualized,trailing_cash,trailing_yield,cash60,yield60,frequency,ppy,regularity,growth,cut,years,stability,suspension,currency,currency_consistent,cutoff.isoformat())

    @staticmethod
    def _classify_frequency(days:float)->tuple[str,float|None]:
        for name,expected,tolerance in (("monthly",30.44,10.0),("quarterly",91.31,25.0),("semiannual",182.62,40.0),("annual",365.24,70.0)):
            if abs(days-expected)<=tolerance: return name,expected
        return "irregular",None
