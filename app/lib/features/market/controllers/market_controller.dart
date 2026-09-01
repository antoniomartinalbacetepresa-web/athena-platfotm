import 'package:flutter/foundation.dart';

import '../models/market_quote.dart';
import '../repositories/market_repository.dart';

class MarketController extends ChangeNotifier {
  final MarketRepository repository;

  MarketQuote? _quote;
  bool _isLoading = false;
  String? _error;

  MarketController({
    required this.repository,
  });

  MarketQuote? get quote => _quote;

  bool get isLoading => _isLoading;

  String? get error => _error;

  Future<void> loadQuote(String symbol) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      _error = 'El símbolo de la acción no puede estar vacío.';
      _quote = null;
      notifyListeners();
      return;
    }

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _quote = await repository.getQuote(normalizedSymbol);
    } catch (e) {
      _quote = null;
      _error = 'No se pudo obtener la cotización.';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}