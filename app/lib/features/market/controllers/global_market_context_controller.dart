import 'package:flutter/foundation.dart';

import '../models/global_market_context.dart';
import '../services/global_market_data_service.dart';

/// Controlador del contexto global del mercado.
///
/// Coordina la obtención del contexto global mediante
/// GlobalMarketDataService y mantiene una frontera fail-closed para la UI.
class GlobalMarketContextController extends ChangeNotifier {
  final GlobalMarketDataService service;

  GlobalMarketContext? _context;
  bool _isLoading = false;
  String? _error;
  int _requestVersion = 0;
  bool _disposed = false;

  GlobalMarketContextController({required this.service});

  GlobalMarketContext? get context => _context;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadGlobalContext() async {
    if (_disposed) {
      return;
    }
    // A new explicit refresh supersedes a stalled request without a clear().
    final requestVersion = ++_requestVersion;

    // A refresh must never keep presenting an old market snapshot as current.
    // Clear it before the asynchronous request starts, matching the fail-closed
    // behaviour of the canonical ATHENA synthesis surface.
    _isLoading = true;
    _error = null;
    _context = null;
    notifyListeners();

    try {
      final nextContext = await service.getGlobalContext();
      if (!_disposed && requestVersion == _requestVersion) {
        _context = nextContext;
      }
    } catch (_) {
      // Provider exceptions may contain request URLs, credentials or private
      // diagnostics. Never expose their raw text through the UI or logs.
      if (!_disposed && requestVersion == _requestVersion) {
        _context = null;
        _error = 'No se pudo verificar el contexto global del mercado. Reintenta la consulta.';
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
    // Invalidate in-flight responses before another market snapshot can load.
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
