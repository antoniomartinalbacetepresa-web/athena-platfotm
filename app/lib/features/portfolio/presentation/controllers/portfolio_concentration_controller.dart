import 'package:flutter/foundation.dart';

import '../../models/portfolio_concentration_snapshot.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_concentration_service.dart';

typedef PortfolioConcentrationLoader = Future<PortfolioConcentrationSnapshot>
    Function({
  required List<PortfolioPosition> positions,
  required String baseCurrency,
});

/// Controls descriptive portfolio concentration without turning concentration
/// into a risk label, diversification claim or investment recommendation.
class PortfolioConcentrationController extends ChangeNotifier {
  final PortfolioConcentrationLoader loadConcentration;

  PortfolioConcentrationSnapshot? _snapshot;
  bool _isLoading = false;
  String? _error;
  int _requestGeneration = 0;
  bool _isDisposed = false;

  PortfolioConcentrationController({required this.loadConcentration});

  factory PortfolioConcentrationController.forService(
    PortfolioConcentrationService service,
  ) {
    return PortfolioConcentrationController(
      loadConcentration: service.analyze,
    );
  }

  PortfolioConcentrationSnapshot? get snapshot => _snapshot;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> load({
    required List<PortfolioPosition> positions,
    String baseCurrency = 'EUR',
  }) async {
    if (_isDisposed) return;
    if (positions.isEmpty) {
      clear();
      return;
    }

    final generation = ++_requestGeneration;
    _snapshot = null;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final next = await loadConcentration(
        positions: List.unmodifiable(positions),
        baseCurrency: baseCurrency,
      );
      if (_isDisposed || generation != _requestGeneration) return;
      _snapshot = next;
      _error = null;
    } catch (_) {
      if (_isDisposed || generation != _requestGeneration) return;
      _snapshot = null;
      _error =
          'No se pudo calcular una concentración verificable de la cartera.';
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
    _snapshot = null;
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
