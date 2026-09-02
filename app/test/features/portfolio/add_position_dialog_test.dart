import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/widgets/add_position_dialog.dart';

class FakeMarketRepository implements MarketRepository {
  String? requestedSymbol;

  @override
  Future<MarketQuote> getQuote(String symbol) async {
    requestedSymbol = symbol;
    return MarketQuote(
      symbol: symbol,
      companyName: 'Verified company',
      currentPrice: 432.10,
      change: 1.0,
      changePercentage: 0.2,
      updatedAt: DateTime.utc(2026, 9, 2, 16, 30),
    );
  }
}

void main() {
  testWidgets(
    'obtiene el precio actual del backend y no permite introducirlo manualmente',
    (tester) async {
      final repository = FakeMarketRepository();
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

      expect(find.text('Precio actual'), findsNothing);
      expect(
        find.textContaining('El precio actual se obtiene del backend de ATHENA'),
        findsOneWidget,
      );

      await tester.enterText(
        find.widgetWithText(TextFormField, 'Ticker'),
        'msft',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Empresa'),
        'Microsoft',
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

      expect(repository.requestedSymbol, 'MSFT');
      expect(result, isNotNull);
      expect(result!.symbol, 'MSFT');
      expect(result!.currentPrice, 432.10);
      expect(result!.currentPriceUpdatedAt, DateTime.utc(2026, 9, 2, 16, 30));
    },
  );
}
