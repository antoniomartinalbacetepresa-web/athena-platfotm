"""Exact provider listing match never guesses canonical identity."""
from app.services.market_quote_identity_service import MarketQuoteIdentityService


class StubRepository:
    def __init__(self, row):
        self.row = row
        self.lookups = []

    def get_by_listing(self, symbol, exchange_short_name):
        self.lookups.append((symbol, exchange_short_name))
        return self.row


ROW = {
    "id": 17, "symbol": "AAPL", "exchange_short_name": "NMS",
    "currency": "USD", "instrument_type": "stock", "is_active": 1,
}
QUOTE = {
    "symbol": " aapl ", "exchange": "nms", "currency": "usd",
    "quoteType": "EQUITY", "sourceProvider": "yahoo",
}


def test_exact_active_listing_returns_internal_id():
    repo = StubRepository(dict(ROW))
    assert MarketQuoteIdentityService(repo).resolve(dict(QUOTE)) == {
        "canonicalIdentityStatus": "matched_internal_listing", "instrumentId": 17,
    }
    assert repo.lookups == [("AAPL", "NMS")]


def test_missing_exchange_never_guesses_from_symbol():
    repo = StubRepository(dict(ROW))
    assert MarketQuoteIdentityService(repo).resolve({**QUOTE, "exchange": None}) == {
        "canonicalIdentityStatus": "unresolved",
    }
    assert repo.lookups == []


def test_currency_mismatch_and_inactive_rows_fail_closed():
    for changed in ({"currency": "EUR"}, {"is_active": 0}):
        repo = StubRepository({**ROW, **changed})
        assert MarketQuoteIdentityService(repo).resolve(dict(QUOTE)) == {
            "canonicalIdentityStatus": "unresolved",
        }


def test_unapproved_exchange_alias_or_wrong_quote_type_fails_closed():
    for changed in (
        {"exchange": "NASDAQ"}, {"quoteType": "ETF"},
        {"sourceProvider": "untrusted"},
    ):
        repo = StubRepository(dict(ROW))
        assert MarketQuoteIdentityService(repo).resolve({**QUOTE, **changed}) == {
            "canonicalIdentityStatus": "unresolved",
        }


def test_invalid_internal_identity_or_instrument_type_fails_closed():
    for changed in (
        {"id": 0}, {"id": True}, {"symbol": "MSFT"},
        {"exchange_short_name": "NYSE"}, {"instrument_type": "etf"},
    ):
        repo = StubRepository({**ROW, **changed})
        assert MarketQuoteIdentityService(repo).resolve(dict(QUOTE)) == {
            "canonicalIdentityStatus": "unresolved",
        }
