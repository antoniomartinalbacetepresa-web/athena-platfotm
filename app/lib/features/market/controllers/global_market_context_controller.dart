import 'package:flutter/foundation.dart';

import '../models/global_market_context.dart';
import '../services/global_market_data_service.dart';

/// Controlador del contexto global del mercado.
///
/// Coordina la obtención del contexto global mediante
/// GlobalMarketDataService.
///
/// No conoce:
/// - el universo de activos;
/// - los pesos regionales;
/// - los benchmarks;
/// - la fuente de datos;
/// - las reglas de cálculo.
///
/// Su responsabilidad es únicamente gestionar el estado
/// que necesita la interfaz.
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

    _isLoading = true;
    _error = null;

    notifyListeners();

    try {
      _context = await service.getGlobalContext();
    } catch (error, stackTrace) {
      debugPrint('ERROR AL OBTENER EL CONTEXTO GLOBAL DEL MERCADO:');
      debugPrint(error.toString());
      debugPrint(stackTrace.toString());

      _context = null;

      // Durante desarrollo mostramos el error real.
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
