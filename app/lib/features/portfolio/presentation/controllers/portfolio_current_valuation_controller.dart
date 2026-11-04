import 'package:flutter/foundation.dart';

import '../../../market/di/market_dependencies.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_current_valuation_service.dart';

typedef PortfolioCurrentValuationLoader = Future<PortfolioCurrentValuation>
    Function({
  required List<PortfolioPosition> positions,
  required String baseCurrency,
});

/// Controls current portfolio valuation without allowing stale async results to
/// overwrite newer portfolio state.
class PortfolioCurrentValuationController extends ChangeNotifier {
  final PortfolioCurrentValuationLoader loadValuation;

  PortfolioCurrentValuation? _valuation;
  bool _isLoading = false;
  String? _error;
  int _requestGeneration = 0;
  bool _isDisposed = false;

  PortfolioCurrentValuationController({
    required this.loadValuation,
  });

  factory PortfolioCurrentValuationController.forService(
    PortfolioCurrentValuationService service,
  ) {
    return PortfolioCurrentValuationController(
      loadValuation: service.value,
    );
  }

  /// Composes current and historical FX only through the configured ATHENA
  /// backend. No nominal or direct-provider conversion is allowed in Flutter.
  factory PortfolioCurrentValuationController.forMarketDependencies(
    MarketDependencies dependencies,
  ) {
    final fxDataSource = dependencies.backendFxDataSource;
    if (fxDataSource == null) {
      throw StateError(
        'La valoración multimoneda requiere FX verificable del backend ATHENA.',
      );
    }

    return PortfolioCurrentValuationController.forService(
      PortfolioCurrentValuationService(
        loadCurrentFxRate: fxDataSource.getCurrentRate,
        loadHistoricalFxRate: ({
          required baseCurrency,
          required quoteCurrency,
          required observedOn,
        }) =>
            fxDataSource.getHistoricalRate(
          baseCurrency: baseCurrency,
          quoteCurrency: quoteCurrency,
          observedOn: observedOn,
        ),
      ),
    );
  }

  PortfolioCurrentValuation? get valuation => _valuation;

  bool get isLoading => _isLoading;

  String? get error => _error;

  Future<void> load({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    if (_isDisposed) return;

    final generation = ++_requestGeneration;

    _valuation = null;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final next = await loadValuation(
        positions: List.unmodifiable(positions),
        baseCurrency: baseCurrency,
      );

      if (_isDisposed || generation != _requestGeneration) return;

      _valuation = next;
      _error = null;
    } catch (_) {
      if (_isDisposed || generation != _requestGeneration) return;

      _valuation = null;
      _error =
          'No se pudo obtener una valoración actual verificable de la cartera.';
    } finally {
      if (!_isDisposed && generation == _requestGeneration) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  void clear() {
    if (_isDisposed) return;

    _requestGeneration++;
    _valuation = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    if (_isDisposed) return;

    _isDisposed = true;
    _requestGeneration++;
    super.dispose();
  }
}
