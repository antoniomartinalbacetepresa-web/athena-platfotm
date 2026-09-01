import yfinance as yf
from yfinance import EquityQuery


REGIONS = [
    ("us", "Estados Unidos"),
    ("ca", "Canadá"),
    ("gb", "Reino Unido"),
    ("de", "Alemania"),
    ("fr", "Francia"),
    ("es", "España"),
    ("it", "Italia"),
    ("ch", "Suiza"),
    ("nl", "Países Bajos"),
    ("jp", "Japón"),
    ("hk", "Hong Kong"),
    ("cn", "China"),
    ("kr", "Corea del Sur"),
    ("tw", "Taiwán"),
    ("in", "India"),
    ("au", "Australia"),
    ("sg", "Singapur"),
    ("br", "Brasil"),
    ("mx", "México"),
]


def test_region(code, name):
    print()
    print("=" * 70)
    print(f"{name} ({code})")
    print("=" * 70)

    try:
        query = EquityQuery(
            "and",
            [
                EquityQuery("eq", ["region", code]),
                EquityQuery("gt", ["intradaymarketcap", 0]),
            ],
        )

        result = yf.screen(
            query,
            offset=0,
            size=10,
            sortField="intradaymarketcap",
            sortAsc=False,
        )

        if not isinstance(result, dict):
            print("TIPO INESPERADO:", type(result))
            return

        quotes = result.get("quotes", [])

        print("Total informado por Yahoo:", result.get("total"))
        print("Resultados recibidos:", len(quotes))

        if not quotes:
            print("SIN RESULTADOS")
            return

        for i, quote in enumerate(quotes, start=1):
            print(
                f"{i:02d}. "
                f"{quote.get('symbol')} | "
                f"{quote.get('shortName') or quote.get('longName')} | "
                f"exchange={quote.get('exchange')} | "
                f"marketCap={quote.get('marketCap')} | "
                f"currency={quote.get('currency')}"
            )

    except Exception as e:
        print("ERROR:", type(e).__name__)
        print(str(e))


def main():
    print("yfinance:", yf.__version__)
    print()
    print("PRUEBA DE COBERTURA GLOBAL DE YAHOO FINANCE")
    print()

    for code, name in REGIONS:
        test_region(code, name)


if __name__ == "__main__":
    main()