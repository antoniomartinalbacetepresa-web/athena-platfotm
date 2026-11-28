import 'package:flutter/foundation.dart';

import '../models/market_context.dart';
import '../repositories/market_context_repository.dart';

/// Fail-closed context state: only the newest request may publish evidence.
class MarketContextController extends ChangeNotifier {
  final MarketContextRepository repository;

  MarketContext? _context;
  bool _isLoading = false;
  String? _error;
  int _requestVersion = 0;
  bool _disposed = false;

  MarketContextController({required this.repository});

  MarketContext? get context => _context;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadMarketContext() async {
    if (_disposed) return;
    // An explicit refresh supersedes even a stalled earlier request.
    final requestVersion = ++_requestVersion;
    _isLoading = true;
    _error = null;
    _context = null;
    notifyListeners();

    try {
      final nextContext = await repository.getMarketContext();
      if (!_disposed && requestVersion == _requestVersion) {
        _context = nextContext;
      }
    } catch (_) {
      // Never expose transport errors or stale evidence to the presentation.
      if (!_disposed && requestVersion == _requestVersion) {
        _context = null;
        _error = 'No se pudo obtener el contexto del mercado.';
      }
    } finally {
      if (!_disposed && requestVersion == _requestVersion) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  void clear() {
    if (_disposed) return;
    _requestVersion++;
    _context = null;
    _error = null;
    _isLoading = false;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _requestVersion++;
    super.dispose();
  }
}
