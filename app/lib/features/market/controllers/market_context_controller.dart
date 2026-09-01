import 'package:flutter/foundation.dart';

import '../models/market_context.dart';
import '../repositories/market_context_repository.dart';

class MarketContextController extends ChangeNotifier {
  final MarketContextRepository repository;

  MarketContext? _context;
  bool _isLoading = false;
  String? _error;

  MarketContextController({
    required this.repository,
  });

  MarketContext? get context => _context;

  bool get isLoading => _isLoading;

  String? get error => _error;

  Future<void> loadMarketContext() async {
    _isLoading = true;
    _error = null;

    notifyListeners();

    try {
      _context = await repository.getMarketContext();
    } catch (e) {
      _context = null;
      _error = 'No se pudo obtener el contexto del mercado.';
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