from app.services.yahoo_fx_service import YahooFxService


def test_fx_rate_is_cached_per_currency(monkeypatch) -> None:
    service = YahooFxService()
    calls: list[str] = []

    def fake_price(symbol: str) -> float:
        calls.append(symbol)
        return 1.2

    monkeypatch.setattr(
        service,
        "_get_positive_last_price",
        fake_price,
    )

    first = service.convert_to_usd(amount=100, currency="EUR")
    second = service.convert_to_usd(amount=200, currency="eur")

    assert first == 120.0
    assert second == 240.0
    assert calls == ["EURUSD=X"]


def test_clear_cache_forces_new_fx_lookup(monkeypatch) -> None:
    service = YahooFxService()
    calls: list[str] = []

    def fake_price(symbol: str) -> float:
        calls.append(symbol)
        return 1.2

    monkeypatch.setattr(
        service,
        "_get_positive_last_price",
        fake_price,
    )

    service.get_usd_rate("EUR")
    service.clear_cache()
    service.get_usd_rate("EUR")

    assert calls == ["EURUSD=X", "EURUSD=X"]
