import yfinance as yf
from yfinance import EquityQuery

print("yfinance:", yf.__version__)

try:
    query = EquityQuery(
        "and",
        [
            EquityQuery("eq", ["region", "us"]),
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

    print("\nTIPO:", type(result))

    if isinstance(result, dict):
        print("CLAVES:", list(result.keys()))

        quotes = result.get("quotes", [])

        print("NUMERO DE RESULTADOS:", len(quotes))

        if quotes:
            print("\nPRIMER RESULTADO COMPLETO:")
            print(quotes[0])

            print("\nCAMPOS DEL PRIMER RESULTADO:")
            for key in sorted(quotes[0].keys()):
                print(" -", key)

except Exception as e:
    print("\nERROR:", type(e).__name__)
    print(str(e))
