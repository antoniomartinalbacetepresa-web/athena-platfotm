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

  GlobalMarketContextController({required this.service});

  GlobalMarketContext? get context => _context;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadGlobalContext() async {
    if (_isLoading) {
      return;
    }

    // A refresh must never keep presenting an old market snapshot as current.
    // Clear it before the asynchronous request starts, matching the fail-closed
    // behaviour of the canonical ATHENA synthesis surface.
    _isLoading = true;
    _error = null;
    _context = null;
    notifyListeners();

    try {
      _context = await service.getGlobalContext();
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER EL CONTEXTO GLOBAL DEL MERCADO:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());
      _context = null;
      _error = 'Error: ${error.toString()}';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  void clear() {
    _context = null;
    _error = null;
    _isLoading = false;
    notifyListeners();
  }
}
