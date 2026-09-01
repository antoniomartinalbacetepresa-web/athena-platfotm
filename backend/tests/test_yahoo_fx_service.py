import pytest

from app.services.yahoo_fx_service import (
    FxRate,
    YahooFxService,
)


def test_get_usd_rate_for_usd_returns_identity() -> None:
    service = YahooFxService()

    result = service.get_usd_rate(
        "USD"
    )

    assert result == FxRate(
        currency="USD",
        usd_rate=1.0,
        source_symbol="USD",
    )


def test_get_usd_rate_normalizes_currency() -> None:
    service = YahooFxService()

    result = service.get_usd_rate(
        "  usd  "
    )

    assert result.currency == "USD"
    assert result.usd_rate == 1.0
    assert result.source_symbol == "USD"


def test_get_usd_rate_uses_direct_pair(
    monkeypatch,
) -> None:
    service = YahooFxService()

    monkeypatch.setattr(
        service,
        "_get_positive_last_price",
        lambda symbol: 1.16,
    )

    result = service.get_usd_rate(
        "EUR"
    )

    assert result == FxRate(
        currency="EUR",
        usd_rate=1.16,
        source_symbol="EURUSD=X",
    )


def test_get_usd_rate_uses_inverse_pair(
    monkeypatch,
) -> None:
    service = YahooFxService()

    monkeypatch.setattr(
        service,
        "_get_positive_last_price",
        lambda symbol: 160.0,
    )

    result = service.get_usd_rate(
        "JPY"
    )

    assert result.currency == "JPY"
    assert result.usd_rate == pytest.approx(
        1.0 / 160.0
    )
    assert result.source_symbol == "JPY=X"


def test_convert_to_usd_for_eur(
    monkeypatch,
) -> None:
    service = YahooFxService()

    monkeypatch.setattr(
        service,
        "get_usd_rate",
        lambda currency: FxRate(
            currency="EUR",
            usd_rate=1.2,
            source_symbol="EURUSD=X",
        ),
    )

    result = service.convert_to_usd(
        amount=100.0,
        currency="EUR",
    )

    assert result == 120.0


def test_convert_to_usd_for_jpy(
    monkeypatch,
) -> None:
    service = YahooFxService()

    monkeypatch.setattr(
        service,
        "get_usd_rate",
        lambda currency: FxRate(
            currency="JPY",
            usd_rate=0.00625,
            source_symbol="JPY=X",
        ),
    )

    result = service.convert_to_usd(
        amount=16000.0,
        currency="JPY",
    )

    assert result == 100.0


def test_get_usd_rate_rejects_unsupported_currency() -> None:
    service = YahooFxService()

    with pytest.raises(
        ValueError,
        match=(
            "No existe una conversión a USD configurada "
            "para la moneda GBP."
        ),
    ):
        service.get_usd_rate(
            "GBP"
        )


def test_normalize_currency_rejects_empty_value() -> None:
    service = YahooFxService()

    with pytest.raises(
        ValueError,
        match="La moneda no puede estar vacía.",
    ):
        service._normalize_currency(
            "   "
        )


def test_convert_to_usd_rejects_zero_amount() -> None:
    service = YahooFxService()

    with pytest.raises(
        ValueError,
        match=(
            "El importe debe ser un número positivo."
        ),
    ):
        service.convert_to_usd(
            amount=0,
            currency="USD",
        )


def test_convert_to_usd_rejects_negative_amount() -> None:
    service = YahooFxService()

    with pytest.raises(
        ValueError,
        match=(
            "El importe debe ser un número positivo."
        ),
    ):
        service.convert_to_usd(
            amount=-100,
            currency="USD",
        )


def test_get_positive_last_price_reads_current_key(
    monkeypatch,
) -> None:
    service = YahooFxService()

    class FakeFastInfo:
        def get(self, key: str):
            values = {
                "lastPrice": 1.15,
                "last_price": None,
            }

            return values.get(key)

    class FakeTicker:
        @property
        def fast_info(self):
            return FakeFastInfo()

    monkeypatch.setattr(
        "app.services.yahoo_fx_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service._get_positive_last_price(
        "EURUSD=X"
    )

    assert result == 1.15


def test_get_positive_last_price_supports_legacy_key(
    monkeypatch,
) -> None:
    service = YahooFxService()

    class FakeFastInfo:
        def get(self, key: str):
            values = {
                "lastPrice": None,
                "last_price": 1.14,
            }

            return values.get(key)

    class FakeTicker:
        @property
        def fast_info(self):
            return FakeFastInfo()

    monkeypatch.setattr(
        "app.services.yahoo_fx_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    result = service._get_positive_last_price(
        "EURUSD=X"
    )

    assert result == 1.14


def test_get_positive_last_price_returns_error_for_invalid_value(
    monkeypatch,
) -> None:
    service = YahooFxService()

    class FakeFastInfo:
        def get(self, key: str):
            return None

    class FakeTicker:
        @property
        def fast_info(self):
            return FakeFastInfo()

    monkeypatch.setattr(
        "app.services.yahoo_fx_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "Yahoo no devolvió un tipo de cambio válido "
            "para EURUSD=X."
        ),
    ):
        service._get_positive_last_price(
            "EURUSD=X"
        )


def test_get_positive_last_price_returns_error_when_yahoo_fails(
    monkeypatch,
) -> None:
    service = YahooFxService()

    class FakeTicker:
        @property
        def fast_info(self):
            raise RuntimeError(
                "Yahoo unavailable"
            )

    monkeypatch.setattr(
        "app.services.yahoo_fx_service.yf.Ticker",
        lambda symbol: FakeTicker(),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "No se pudo obtener el tipo de cambio "
            "para EURUSD=X."
        ),
    ):
        service._get_positive_last_price(
            "EURUSD=X"
        )
