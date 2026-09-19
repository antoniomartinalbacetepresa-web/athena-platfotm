import 'package:flutter/foundation.dart';

import '../../models/authenticated_portfolio_view_position.dart';
import '../../services/authenticated_portfolio_fx_valuation_service.dart';

/// Fail-closed presentation state for authenticated Portfolio FX valuation.
///
/// This controller never retains a previous monetary total while a new
/// authoritative valuation is loading or after valuation/provenance failure.
class AuthenticatedPortfolioFxValuationController extends ChangeNotifier {
  AuthenticatedPortfolioFxValuationController({
    required this._valuationService,
  });

  final AuthenticatedPortfolioFxValuationService _valuationService;

  bool _isLoading = false;
  String? _error;
  AuthenticatedPortfolioFxValuation? _valuation;
  int _generation = 0;

  bool get isLoading => _isLoading;
  String? get error => _error;
  AuthenticatedPortfolioFxValuation? get valuation => _valuation;
  bool get hasVerifiedValuation => _valuation != null && _error == null;

  Future<void> load({
    required List<AuthenticatedPortfolioViewPosition> positions,
    required String baseCurrency,
  }) async {
    final generation = ++_generation;
    _isLoading = true;
    _error = null;
    _valuation = null;
    notifyListeners();

    try {
      final next = await _valuationService.value(
        positions: List<AuthenticatedPortfolioViewPosition>.unmodifiable(positions),
        baseCurrency: baseCurrency,
      );
      if (generation != _generation) return;
      _valuation = next;
    } catch (_) {
      if (generation != _generation) return;
      _error = 'No se pudo verificar la valoración multidivisa de la cartera.';
      _valuation = null;
    } finally {
      if (generation == _generation) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  void clear() {
    _generation++;
    _isLoading = false;
    _error = null;
    _valuation = null;
    notifyListeners();
  }
}