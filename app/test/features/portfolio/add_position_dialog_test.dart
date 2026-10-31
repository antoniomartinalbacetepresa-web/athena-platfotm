import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/models/portfolio_instrument_identity.dart';
import 'package:app/features/portfolio/services/portfolio_identity_enrichment_service.dart';
import 'package:app/features/portfolio/widgets/add_position_dialog.dart';

class FakeMarketRepository implements MarketRepository {
  FakeMarketRepository({MarketQuote? quote}) : quote = quote ?? _validQuote();

  MarketQuote quote;
  String? requestedSymbol;

  static MarketQuote _validQuote() {
    return MarketQuote(
      symbol: 'MSFT',
      companyName: 'Verified company',
      currentPrice: 432.10,
      change: 1.0,
      changePercentage: 0.2,
      currency: 'usd',
      exchange: 'NMS',
      quoteType: 'EQUITY',
      updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
      sourceProvider: 'yahoo',
      retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
    );
  }

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    requestedSymbol = symbol;
    return quote;
  }
}

PortfolioInstrumentIdentity validIdentity({
  String symbol = 'MSFT',
  String exchange = 'NMS',
  String currency = 'USD',
  bool exchangeVerified = true,
  bool riskReady = true,
}) {
  return PortfolioInstrumentIdentity(
    databaseInstrumentId: 42,
    canonicalInstrumentId: '$symbol@$exchange',
    issuerId: 'issuer:microsoft',
    symbol: symbol,
    exchange: exchange,
    exchangeShortName: exchange,
    currency: currency,
    sourceProvider: 'yahoo_catalog',
    retrievedAt: DateTime.utc(2026, 9, 2, 16, 32),
    resolutionMethod: 'symbol_and_exchange_exact',
    exchangeVerified: exchangeVerified,
    isRiskReady: riskReady,
    isWeightingReady: false,
    recommendationPolicy: 'no_advice',
    productionEligible: false,
    automaticTrading: false,
  );
}

Future<AddPositionResult?> openAndSubmit(
  WidgetTester tester,
  FakeMarketRepository repository, {
  String? costBasisDate,
  PortfolioIdentityResolver? identityResolver,
}) async {
  AddPositionResult? result;

  await tester.pumpWidget(
    MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: ElevatedButton(
            onPressed: () async {
              result = await showDialog<AddPositionResult>(
                context: context,
                builder: (_) => AddPositionDialog(
                  marketRepository: repository,
                  identityResolver: identityResolver ??
                      ({required symbol, exchange}) async {
                        expect(symbol, 'MSFT');
                        expect(exchange, 'NMS');
                        return validIdentity();
                      },
                ),
              );
            },
            child: const Text('Abrir'),
          ),
        ),
      ),
    ),
  );

  await tester.tap(find.text('Abrir'));
  await tester.pumpAndSettle();

  await tester.enterText(
    find.widgetWithText(TextFormField, 'Ticker'),
    'msft',
  );
  await tester.enterText(
    find.widgetWithText(TextFormField, 'Número de acciones'),
    '2',
  );
  await tester.enterText(
    find.widgetWithText(TextFormField, 'Precio medio de compra'),
    '400',
  );
  if (costBasisDate != null) {
    await tester.enterText(
      find.widgetWithText(
        TextFormField,
        'Fecha del coste (AAAA-MM-DD, opcional)',
      ),
      costBasisDate,
    );
  }

  await tester.tap(find.text('Guardar posición'));
  await tester.pumpAndSettle();

  return result;
}

void main() {
  testWidgets(
    'obtiene precio listing identidad canónica y provenance sin campos manuales',
    (tester) async {
      final repository = FakeMarketRepository();

      final result = await openAndSubmit(tester, repository);

      expect(find.text('Precio actual'), findsNothing);
      expect(find.text('Empresa'), findsNothing);
      expect(repository.requestedSymbol, 'MSFT');
      expect(result, isNotNull);
      expect(result!.symbol, 'MSFT');
      expect(result.companyName, 'Verified company');
      expect(result.currentPrice, 432.10);
      expect(result.costBasisDate, isNull);
      expect(result.priceCurrency, 'USD');
      expect(result.exchange, 'NMS');
      expect(result.quoteType, 'EQUITY');
      expect(result.currentPriceUpdatedAt, DateTime.utc(2026, 9, 2, 16, 30));
      expect(result.currentPriceSourceProvider, 'yahoo');
      expect(result.currentPriceRetrievedAt, DateTime.utc(2026, 9, 2, 16, 31));
      expect(result.databaseInstrumentId, 42);
      expect(result.canonicalInstrumentId, 'MSFT@NMS');
      expect(result.canonicalIssuerId, 'issuer:microsoft');
      expect(result.identitySourceProvider, 'yahoo_catalog');
      expect(result.identityRetrievedAt, DateTime.utc(2026, 9, 2, 16, 32));
      expect(result.identityResolutionMethod, 'symbol_and_exchange_exact');
      expect(result.identityExchangeVerified, isTrue);
      expect(result.identityRiskReady, isTrue);
    },
  );

  testWidgets('conserva fecha de coste explícita sin inferirla', (tester) async {
    final repository = FakeMarketRepository();

    final result = await openAndSubmit(
      tester,
      repository,
      costBasisDate: '2026-08-15',
    );

    expect(result, isNotNull);
    expect(result!.costBasisDate, DateTime.utc(2026, 8, 15));
  });

  testWidgets('rechaza fecha de coste futura', (tester) async {
    final repository = FakeMarketRepository();

    final result = await openAndSubmit(
      tester,
      repository,
      costBasisDate: '2999-01-01',
    );

    expect(result, isNull);
    expect(find.textContaining('no puede estar en el futuro'), findsOneWidget);
    expect(repository.requestedSymbol, isNull);
  });

  testWidgets('rechaza fecha de coste calendario inválida', (tester) async {
    final repository = FakeMarketRepository();

    final result = await openAndSubmit(
      tester,
      repository,
      costBasisDate: '2026-02-31',
    );

    expect(result, isNull);
    expect(find.textContaining('fecha válida'), findsOneWidget);
    expect(repository.requestedSymbol, isNull);
  });

  testWidgets('rechaza cotización sin proveedor verificable', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'MSFT',
        companyName: 'Verified company',
        currentPrice: 432.10,
        change: 1.0,
        changePercentage: 0.2,
        currency: 'USD',
        exchange: 'NMS',
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });

  testWidgets('rechaza recuperación anterior a la observación', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'MSFT',
        companyName: 'Verified company',
        currentPrice: 432.10,
        change: 1.0,
        changePercentage: 0.2,
        currency: 'USD',
        exchange: 'NMS',
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        sourceProvider: 'yahoo',
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 29),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });

  testWidgets('rechaza símbolo distinto al solicitado', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'AAPL',
        companyName: 'Wrong company',
        currentPrice: 200,
        change: 1,
        changePercentage: 0.5,
        currency: 'USD',
        exchange: 'NMS',
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        sourceProvider: 'yahoo',
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });

  testWidgets('rechaza cotización sin moneda verificable', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'MSFT',
        companyName: 'Verified company',
        currentPrice: 432.10,
        change: 1,
        changePercentage: 0.2,
        exchange: 'NMS',
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        sourceProvider: 'yahoo',
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });

  testWidgets('rechaza código de moneda no ISO de tres letras', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'MSFT',
        companyName: 'Verified company',
        currentPrice: 432.10,
        change: 1,
        changePercentage: 0.2,
        currency: r'US$',
        exchange: 'NMS',
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        sourceProvider: 'yahoo',
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });

  testWidgets('rechaza identidad canónica no apta para riesgo', (tester) async {
    final repository = FakeMarketRepository();

    final result = await openAndSubmit(
      tester,
      repository,
      identityResolver: ({required symbol, exchange}) async =>
          validIdentity(exchangeVerified: false, riskReady: false),
    );

    expect(result, isNull);
    expect(find.textContaining('identidad canónica'), findsWidgets);
  });
}
