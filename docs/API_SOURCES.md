# ATHENA TYCHE — Data Source Registry

This file is the canonical inventory of external data sources used or planned by ATHENA TYCHE.

## Architecture rule

Flutter must not depend directly on external financial providers. External data is acquired by the ATHENA backend, normalized, timestamped, validated, stored when appropriate and then exposed to Flutter and ATHENA engines through stable internal contracts.

Every persisted observation should ultimately preserve at least:

- `source_id`
- `retrieved_at`
- `published_at` when available
- `effective_at` / observation date
- source-native identifier or version when available
- quality/validation status

ATHENA must distinguish facts from derived calculations and predictions. Historical backtests must avoid look-ahead, survivorship, revision and data-leakage biases.

## Integration states

- `connected`: production code already talks to the source.
- `ready_to_integrate`: public official interface is suitable; connector implementation/normalization is next.
- `credentials_required`: free or acceptable access exists but backend-only credentials/configuration are required.
- `restricted_access`: useful source exists but official programmatic access is limited.
- `research_required`: licensing, redistribution, coverage or technical access must be resolved before implementation.

The backend exposes the live registry at `GET /api/v1/sources`.

## Source matrix

| Source | Domain | State | Main use |
| --- | --- | --- | --- |
| Yahoo Finance | Market | connected | Quotes, OHLCV history, indices, ETFs, FX |
| Nasdaq Trader | Universe | connected | Listed symbols, exchanges, instruments |
| SEC EDGAR / XBRL | Fundamentals | ready_to_integrate | 10-K, 10-Q, 8-K, 20-F, statements, notes |
| SEC Form 13F | Investors | ready_to_integrate | Institutional holdings and portfolio changes |
| SEC Form 4 | Insiders | ready_to_integrate | Insider purchases, sales and ownership changes |
| FRED / ALFRED | Macro | credentials_required | Rates, inflation, employment and historical vintages |
| ECB Data Portal | Macro | ready_to_integrate | Euro rates, credit, money, FX and macro |
| BLS | Macro | ready_to_integrate | Employment, CPI, wages and productivity |
| BEA | Macro | credentials_required | GDP, income, consumption, profits, industry accounts |
| FINRA | Positioning | ready_to_integrate | Short interest and OTC transparency |
| CFTC COT | Positioning | ready_to_integrate | Futures positioning |
| EIA | Energy | credentials_required | Oil, gas, inventories, production, electricity |
| World Bank | Macro | ready_to_integrate | Country risk, structural growth, demographics, trade |
| OECD | Macro | ready_to_integrate | Leading indicators, productivity, trade and confidence |
| IMF | Macro | ready_to_integrate | Balance of payments, reserves, debt and international macro |
| Google Trends | Alternative | restricted_access | Search/brand interest and emerging topics |
| Google News / publishers | News | research_required | Discovery of company, sector and macro events |
| Google Finance | Verification | research_required | Complementary market-data cross-check only |
| ESMA / Euronext / national exchanges | Europe universe | research_required | ISINs, listings, instruments and corporate actions |
| Companies House | Company registry | credentials_required | UK company and officer/filing metadata |
| USPTO | Innovation | credentials_required | Patents, applications and innovation signals |
| Analyst consensus providers | Analysts | research_required | Ratings, targets, revisions, upgrades/downgrades |

## Provider policy

1. Prefer official/public sources where they materially improve accuracy.
2. Prefer zero-cost access during development.
3. Do not add redundant paid market-data vendors merely to increase provider count.
4. Keep every secret in backend environment/configuration, never in Flutter Web.
5. Do not silently replace a failed real source with mock data in production.
6. Record source freshness and data quality so ATHENA can learn source reliability over time.
7. News must retain the original publisher and deduplicate syndicated copies.
8. 13F holdings are delayed disclosures and must not be represented as current trades.
9. Analyst and exchange data must only be integrated when licensing/redistribution terms permit ATHENA's use.
10. Technical indicators (RSI, MACD, ATR, Bollinger, moving averages, momentum, volatility, drawdown, correlation, beta, etc.) should be calculated by ATHENA from normalized OHLCV rather than purchased as opaque signals.

## Recommended ingestion order

### Foundation

- Yahoo market data
- Nasdaq Trader universe
- SEC EDGAR/XBRL
- SEC 13F
- SEC Form 4
- FRED/ALFRED
- ECB

### Positioning and sector context

- FINRA
- CFTC COT
- EIA
- BLS / BEA

### International macro and coverage

- World Bank
- OECD
- IMF
- European official market/reference sources
- Companies House

### Alternative and opinion signals

- Google Trends
- news sources and original publishers
- USPTO
- analyst consensus
- Google Finance verification

## ATHENA engine mapping

- Market/Technical Engine: Yahoo + normalized OHLCV + exchange universe.
- Fundamental/Quality/Valuation Engines: SEC filings/XBRL plus official international registries where available.
- Investor Engine: SEC 13F.
- Insider Engine: SEC Form 4.
- Macro Engine: FRED/ALFRED, ECB, BLS, BEA, World Bank, OECD, IMF.
- Positioning Engine: FINRA and CFTC COT.
- Energy Context: EIA.
- News/Sentiment Engine: original publishers discovered through approved news channels.
- Alternative Signals: Google Trends and USPTO.
- Analyst Engine: licensed/approved analyst consensus source.

No source by itself generates a buy/sell recommendation. Each source feeds normalized evidence into ATHENA engines; the Recommendation Engine combines evidence, uncertainty, risk and historical calibration and must explain the reasons for agreement or disagreement with investors and analysts.
