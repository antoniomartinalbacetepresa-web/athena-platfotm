import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
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

Future<AddPositionResult?> openAndSubmit(
  WidgetTester tester,
  FakeMarketRepository repository,
) async {
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

  await tester.tap(find.text('Guardar posición'));
  await tester.pumpAndSettle();

  return result;
}

void main() {
  testWidgets(
    'obtiene identidad precio y provenance sin campos manuales',
    (tester) async {
      final repository = FakeMarketRepository();

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: ElevatedButton(
                onPressed: () {},
                child: const Text('placeholder'),
              ),
            ),
          ),
        ),
      );

      final result = await openAndSubmit(tester, repository);

      expect(find.text('Precio actual'), findsNothing);
      expect(find.text('Empresa'), findsNothing);
      expect(repository.requestedSymbol, 'MSFT');
      expect(result, isNotNull);
      expect(result!.symbol, 'MSFT');
      expect(result.companyName, 'Verified company');
      expect(result.currentPrice, 432.10);
      expect(result.currentPriceUpdatedAt, DateTime.utc(2026, 9, 2, 16, 30));
      expect(result.currentPriceSourceProvider, 'yahoo');
      expect(result.currentPriceRetrievedAt, DateTime.utc(2026, 9, 2, 16, 31));
    },
  );

  testWidgets('rechaza cotización sin proveedor verificable', (tester) async {
    final repository = FakeMarketRepository(
      quote: MarketQuote(
        symbol: 'MSFT',
        companyName: 'Verified company',
        currentPrice: 432.10,
        change: 1.0,
        changePercentage: 0.2,
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
        updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
        sourceProvider: 'yahoo',
        retrievedAt: DateTime.utc(2026, 9, 2, 16, 31),
      ),
    );

    final result = await openAndSubmit(tester, repository);

    expect(result, isNull);
    expect(find.textContaining('sin trazabilidad'), findsOneWidget);
  });
}
