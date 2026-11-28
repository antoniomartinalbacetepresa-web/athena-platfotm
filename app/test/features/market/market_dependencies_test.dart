import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/config/market_provider_settings.dart';
import 'package:app/features/market/di/market_dependencies.dart';

void main() {
  test(
    'crea correctamente las dependencias en modo mock explícito',
    () async {
      final dependencies = MarketDependencies.create(
        settings: const MarketProviderSettings.development(),
      );

      expect(dependencies.repository, isNotNull);
      expect(dependencies.marketContextRepository, isNotNull);
      expect(dependencies.marketUniverseRepository, isNotNull);
      expect(dependencies.globalMarketDataService, isNotNull);

      final mockContext = await dependencies.marketContextRepository
          .getMarketContext();
      expect(mockContext.assetsAnalyzed, 500);

      dependencies.dispose();
    },
  );

  test(
    'modo real no puede servir contexto legado ficticio',
    () async {
      final dependencies = MarketDependencies.create(
        settings: MarketProviderSettings.athenaBackend(
          baseUrl: 'http://127.0.0.1:8000',
        ),
      );

      expect(dependencies.backendMarketProvider, isNotNull);
      expect(dependencies.backendUniverseDataSource, isNotNull);
      expect(dependencies.backendFxDataSource, isNotNull);

      await expectLater(
        dependencies.marketContextRepository.getMarketContext(),
        throwsA(
          isA<StateError>().having(
            (error) => error.message,
            'message',
            contains('contexto de mercado legado no está disponible'),
          ),
        ),
      );

      dependencies.dispose();
    },
  );
}
