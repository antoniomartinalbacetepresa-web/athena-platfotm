import 'package:flutter/foundation.dart';

import '../../models/portfolio_correlation_snapshot.dart';
import '../../models/portfolio_position.dart';
import '../../services/portfolio_correlation_evidence_service.dart';

class PortfolioCorrelationController extends ChangeNotifier {
  final PortfolioCorrelationEvidenceService service;

  PortfolioCorrelationSnapshot? _snapshot;
  bool _isLoading = false;
  String? _error;
  int _requestGeneration = 0;
  bool _isDisposed = false;

  PortfolioCorrelationController({required this.service});

  PortfolioCorrelationSnapshot? get snapshot => _snapshot;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> load({
    required List<PortfolioPosition> positions,
    required DateTime knowledgeCutoff,
  }) async {
    if (_isDisposed) return;
    if (positions.length < 2) {
      clear();
      return;
    }

    final generation = ++_requestGeneration;
    _snapshot = null;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final next = await service.analyze(
        positions: List.unmodifiable(positions),
        knowledgeCutoff: knowledgeCutoff,
      );
      if (_isDisposed || generation != _requestGeneration) return;
      _snapshot = next;
      _error = null;
    } catch (_) {
      if (_isDisposed || generation != _requestGeneration) return;
      _snapshot = null;
      _error =
          'No hay correlación PIT verificable para todas las posiciones.';
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
