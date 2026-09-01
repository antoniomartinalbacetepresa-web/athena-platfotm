from __future__ import annotations

import httpx
import pytest

from app.services.nasdaq_trader_universe_source import (
    NasdaqTraderUniverseSource,
)


NASDAQ_LISTED_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ADR1|Example Holdings ADR|Q|N|N|100|N|N
PREF1|Example Corp Preferred Stock|Q|N|N|100|N|N
TESTZ|Nasdaq Test Security|Q|Y|N|100|N|N
File Creation Time: 0830202617:32
"""


OTHER_LISTED_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
AMEX|Example Company Common Stock|A|AMEX|N|100|N|AMEX
BZX1|Example BZX Company Common Shares|Z|BZX1|N|100|N|BZX1
IEX1|Example IEX Company Common Stock|V|IEX1|N|100|N|IEX1
TESTO|Other Test Security|N|TESTO|N|100|Y|TESTO
File Creation Time: 0830202617:32
"""


def _create_client(
    nasdaq_text: str = NASDAQ_LISTED_SAMPLE,
    other_text: str = OTHER_LISTED_SAMPLE,
    nasdaq_status: int = 200,
    other_status: int = 200,
) -> httpx.Client:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        url = str(
            request.url
        )

        if "nasdaqlisted.txt" in url:
            return httpx.Response(
                status_code=nasdaq_status,
                text=nasdaq_text,
                request=request,
            )

        if "otherlisted.txt" in url:
            return httpx.Response(
                status_code=other_status,
                text=other_text,
                request=request,
            )

        return httpx.Response(
            status_code=404,
            request=request,
        )

    return httpx.Client(
        transport=httpx.MockTransport(
            handler
        )
    )


def test_get_instruments_combines_both_files() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        symbols = {
            instrument["symbol"]
            for instrument in instruments
        }

        assert "AAPL" in symbols
        assert "IBM" in symbols
    finally:
        client.close()


def test_source_id_is_nasdaq_trader() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        assert source.source_id == "nasdaq_trader"
    finally:
        client.close()


def test_nasdaq_listing_is_normalized_without_inventing_geography() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        apple = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "AAPL"
        )

        assert apple["companyName"] == (
            "Apple Inc. - Common Stock"
        )
        assert apple["exchange"] == "NASDAQ"
        assert apple["exchangeShortName"] == "NASDAQ"
        assert apple["instrumentType"] == "common_stock"
        assert apple["isPrimaryListing"] is False
        assert apple["sourceProvider"] == "nasdaq_trader"
        assert apple["isActive"] is True

        assert "country" not in apple
        assert "regionKey" not in apple
    finally:
        client.close()


def test_nasdaq_etf_is_classified_as_etf() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        qqq = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "QQQ"
        )

        assert qqq["instrumentType"] == "etf"
    finally:
        client.close()


def test_adr_is_classified_as_adr() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        adr = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "ADR1"
        )

        assert adr["instrumentType"] == "adr"
    finally:
        client.close()


def test_preferred_stock_is_classified() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        preferred = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "PREF1"
        )

        assert (
            preferred["instrumentType"]
            == "preferred_stock"
        )
    finally:
        client.close()


def test_test_issues_are_excluded() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        symbols = {
            instrument["symbol"]
            for instrument in instruments
        }

        assert "TESTZ" not in symbols
        assert "TESTO" not in symbols
    finally:
        client.close()


def test_other_listed_nyse_is_mapped_without_geography() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        ibm = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "IBM"
        )

        assert ibm["exchange"] == "NYSE"
        assert ibm["exchangeShortName"] == "NYSE"
        assert ibm["instrumentType"] == "common_stock"

        assert ibm["isPrimaryListing"] is False
        assert "country" not in ibm
        assert "regionKey" not in ibm
    finally:
        client.close()


def test_other_listed_exchange_codes_are_mapped() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        by_symbol = {
            instrument["symbol"]: instrument
            for instrument in instruments
        }

        assert (
            by_symbol["AMEX"]["exchange"]
            == "NYSE AMERICAN"
        )
        assert (
            by_symbol["AMEX"]["exchangeShortName"]
            == "NYSEAMERICAN"
        )

        assert (
            by_symbol["BZX1"]["exchange"]
            == "CBOE BZX"
        )
        assert (
            by_symbol["BZX1"]["exchangeShortName"]
            == "BZX"
        )

        assert (
            by_symbol["IEX1"]["exchange"]
            == "IEX"
        )
        assert (
            by_symbol["IEX1"]["exchangeShortName"]
            == "IEX"
        )
    finally:
        client.close()


def test_other_listed_etf_is_classified_as_etf() -> None:
    client = _create_client()

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        spy = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "SPY"
        )

        assert spy["instrumentType"] == "etf"
        assert spy["exchange"] == "NYSE ARCA"
        assert spy["exchangeShortName"] == "NYSEARCA"
    finally:
        client.close()


def test_unknown_exchange_code_is_preserved() -> None:
    other_text = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
XYZ|Unknown Exchange Company Common Stock|X|XYZ|N|100|N|XYZ
File Creation Time: 0830202617:32
"""

    client = _create_client(
        other_text=other_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        xyz = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "XYZ"
        )

        assert xyz["exchange"] == "X"
        assert xyz["exchangeShortName"] == "X"
    finally:
        client.close()


def test_empty_download_raises_runtime_error() -> None:
    client = _create_client(
        nasdaq_text="   "
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "Nasdaq Trader devolvió "
                "un fichero vacío."
            ),
        ):
            source.get_instruments()
    finally:
        client.close()


def test_http_failure_is_propagated() -> None:
    client = _create_client(
        nasdaq_status=503
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        with pytest.raises(
            httpx.HTTPStatusError
        ):
            source.get_instruments()
    finally:
        client.close()


def test_unknown_security_type_remains_unknown() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
MYST|Mystery Security|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text,
        other_text=(
            "ACT Symbol|Security Name|Exchange|"
            "CQS Symbol|ETF|Round Lot Size|"
            "Test Issue|NASDAQ Symbol\n"
            "File Creation Time: 0830202617:32\n"
        ),
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        assert len(instruments) == 1
        assert instruments[0]["symbol"] == "MYST"
        assert (
            instruments[0]["instrumentType"]
            == "unknown"
        )
    finally:
        client.close()


def test_warrant_with_trailing_period_is_classified() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
TESTW|Example Acquisition Corp. - Warrant.|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        test_warrant = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "TESTW"
        )

        assert (
            test_warrant["instrumentType"]
            == "warrant"
        )
    finally:
        client.close()


def test_unit_with_trailing_period_is_classified() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
TESTU|Example Acquisition Corp. - Unit.|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        test_unit = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "TESTU"
        )

        assert test_unit["instrumentType"] == "unit"
    finally:
        client.close()


def test_depositary_shares_are_classified() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
DEPO|Example Corporation - Depositary Shares|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        depositary = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "DEPO"
        )

        assert (
            depositary["instrumentType"]
            == "depositary_receipt"
        )
    finally:
        client.close()


def test_junior_subordinated_notes_are_debt() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
DEBT|Example Corporation - 6.25% Junior Subordinated Notes, Series due 2085|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        debt = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "DEBT"
        )

        assert debt["instrumentType"] == "debt"
    finally:
        client.close()


def test_class_a_shares_are_common_stock() -> None:
    other_text = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
CLSA|Example Holdings Class A Shares|N|CLSA|N|100|N|CLSA
File Creation Time: 0830202617:32
"""

    client = _create_client(
        other_text=other_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        class_a = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "CLSA"
        )

        assert (
            class_a["instrumentType"]
            == "common_stock"
        )
    finally:
        client.close()


def test_foreign_security_does_not_infer_country_or_region() -> None:
    nasdaq_text = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
TSM|Taiwan Semiconductor Manufacturing Company Ltd. - ADS|Q|N|N|100|N|N
File Creation Time: 0830202617:32
"""

    client = _create_client(
        nasdaq_text=nasdaq_text
    )

    try:
        source = NasdaqTraderUniverseSource(
            client=client
        )

        instruments = source.get_instruments()

        tsm = next(
            instrument
            for instrument in instruments
            if instrument["symbol"] == "TSM"
        )

        assert tsm["instrumentType"] == "adr"

        assert "country" not in tsm
        assert "regionKey" not in tsm

        assert tsm["isPrimaryListing"] is False
    finally:
        client.close()
