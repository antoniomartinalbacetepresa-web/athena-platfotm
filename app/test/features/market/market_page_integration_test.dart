import 'dart:async';

import 'package:app/features/market/controllers/global_market_context_controller.dart';
import 'package:app/features/market/models/global_market_context.dart';
import 'package:app/features/market/models/market_region.dart';
import 'package:app/features/market/models/market_universe_asset.dart';
import 'package:app/features/market/models/regional_market_context.dart';
import 'package:app/features/market/presentation/pages/market_page.dart';
import 'package:app/features/market/repositories/market_universe_repository.dart';
import 'package:app/features/market/services/global_market_context_service.dart';
import 'package:app/features/market/services/global_market_data_service.dart';
import 'package:app/features/market/services/regional_market_context_service.dart';
import 'package:app/features/market/services/regional_market_weight_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _RegionalService implements RegionalMarketContextService {
  @override
  Future<RegionalMarketContext> getRegionalContext({required MarketRegion region}) async =>
      RegionalMarketContext(
        region: region.key,
        displayName: region.key,
        assetsAnalyzed: 1,
        advancingPercentage: 100,
        decliningPercentage: 0,
        sentiment: 'positive',
        summary: region.key,
        updatedAt: DateTime.utc(2026, 9, 21, 3),
      );
}

class _UniverseRepository implements MarketUniverseRepository {
  const _UniverseRepository();

  @override
  Future<List<MarketUniverseAsset>> getUniverse() async => const [
        MarketUniverseAsset(
          symbol: 'USA',
          companyName: 'America Test Company',
          marketCap: 500,
          country: 'United States',
        ),
        MarketUniverseAsset(
          symbol: 'ESP',
          companyName: 'Europe Test Company',
          marketCap: 300,
          country: 'Spain',
        ),
        MarketUniverseAsset(
          symbol: 'JPN',
          companyName: 'Asia Test Company',
          marketCap: 200,
          country: 'Japan',
        ),
      ];
}

class _ControlledMarketService extends GlobalMarketDataService {
  _ControlledMarketService(this.responses)
      : super(
          regionalMarketContextService: _RegionalService(),
          globalMarketContextService: const GlobalMarketContextService(),
          marketUniverseRepository: const _UniverseRepository(),
          regionalMarketWeightService: const RegionalMarketWeightService(),
        );

  final List<Future<GlobalMarketContext>> responses;
  var calls = 0;

  @override
  Future<GlobalMarketContext> getGlobalContext() => responses[calls++];
}

Future<GlobalMarketContext> _context(String summary) async {
  final base = await GlobalMarketDataService(
    regionalMarketContextService: _RegionalService(),
    globalMarketContextService: const GlobalMarketContextService(),
    marketUniverseRepository: const _UniverseRepository(),
    regionalMarketWeightService: const RegionalMarketWeightService(),
  ).getGlobalContext();
  return GlobalMarketContext(
    updatedAt: base.updatedAt,
    america: base.america,
    europe: base.europe,
    asia: base.asia,
    americaWeight: base.americaWeight,
    europeWeight: base.europeWeight,
    asiaWeight: base.asiaWeight,
    weightSource: base.weightSource,
    weightConfidence: base.weightConfidence,
    marketUniverseStatus: base.marketUniverseStatus,
    advancingPercentage: base.advancingPercentage,
    decliningPercentage: base.decliningPercentage,
    sentiment: base.sentiment,
    summary: summary,
  );
}

void main() {
  testWidgets('Market page hides stale snapshot while refresh is pending', (tester) async {
    final pending = Completer<GlobalMarketContext>();
    final initial = await _context('Snapshot inicial');
    final updated = await _context('Snapshot actualizado');
    final service = _ControlledMarketService([
      Future.value(initial),
      pending.future,
    ]);
    final controller = GlobalMarketContextController(service: service);

    await tester.pumpWidget(MaterialApp(home: MarketPage(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.text('Snapshot inicial'), findsOneWidget);

    await tester.tap(find.byTooltip('Actualizar mercado'));
    await tester.pump();
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    pending.complete(updated);
    await tester.pumpAndSettle();
    expect(find.text('Snapshot actualizado'), findsOneWidget);
    expect(find.text('Snapshot inicial'), findsNothing);
    expect(service.calls, 2);

    controller.dispose();
  });
}
