import 'package:flutter/foundation.dart';

import '../../models/portfolio_position.dart';
import '../../services/portfolio_current_valuation_service.dart';

typedef PortfolioCurrentValuationLoader = Future<PortfolioCurrentValuation>
    Function({
  required List<PortfolioPosition> positions,
  required String baseCurrency,
});

/// Controls current portfolio valuation without allowing stale async results to
/// overwrite newer portfolio state.
///
/// This controller deliberately exposes only *current* valuation. Historical
/// cost basis and P/L remain governed by [PortfolioCurrentValuation], which
/// keeps them unavailable when acquisition-date FX evidence is missing.
class PortfolioCurrentValuationController extends ChangeNotifier {
  final PortfolioCurrentValuationLoader loadValuation;

  PortfolioCurrentValuation? _valuation;
  bool _isLoading = false;
  String? _error;
  int _requestGeneration = 0;

  PortfolioCurrentValuationController({
    required this.loadValuation,
  });

  PortfolioCurrentValuation? get valuation => _valuation;

  bool get isLoading => _isLoading;

  String? get error => _error;

  Future<void> load({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    final generation = ++_requestGeneration;

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final next = await loadValuation(
        positions: List.unmodifiable(positions),
        baseCurrency: baseCurrency,
      );

      if (generation != _requestGeneration) return;

      _valuation = next;
      _error = null;
    } catch (_) {
      if (generation != _requestGeneration) return;

      _valuation = null;
      _error =
          'No se pudo obtener una valoración actual verificable de la cartera.';
    } finally {
      if (generation == _requestGeneration) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  void clear() {
    _requestGeneration++;
    _valuation = null;
    _isLoading = false;
    _error = null;
    notifyListeners();
  }
}
