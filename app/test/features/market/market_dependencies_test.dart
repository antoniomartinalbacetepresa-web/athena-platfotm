import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/market/data/config/market_provider_settings.dart';
import 'package:app/features/market/di/market_dependencies.dart';

void main() {
  test(
    'crea correctamente las dependencias en modo mock explícito',
    () {
      final dependencies = MarketDependencies.create(
        settings: const MarketProviderSettings.development(),
      );

      expect(dependencies.repository, isNotNull);
      expect(dependencies.marketContextRepository, isNotNull);
      expect(dependencies.marketUniverseRepository, isNotNull);
      expect(dependencies.globalMarketDataService, isNotNull);

      dependencies.dispose();
    },
  );
}
