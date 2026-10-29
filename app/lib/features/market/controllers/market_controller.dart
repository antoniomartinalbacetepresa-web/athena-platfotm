import 'package:flutter/foundation.dart';

import '../models/market_quote.dart';
import '../repositories/market_repository.dart';

/// Read-only quote presentation. A response is never authoritative for a
/// different requested symbol or an older request generation.
class MarketController extends ChangeNotifier {
  final MarketRepository repository;

  MarketQuote? _quote;
  bool _isLoading = false;
  String? _error;
  int _requestVersion = 0;
  bool _disposed = false;

  MarketController({required this.repository});

  MarketQuote? get quote => _quote;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> loadQuote(String symbol) async {
    if (_disposed) return;
    final requestVersion = ++_requestVersion;
    final normalizedSymbol = symbol.trim().toUpperCase();

    // Revoke any previous quote immediately. Neither an empty input nor a
    // refresh may leave an old price visible as current evidence.
    _quote = null;
    _error = null;
    if (normalizedSymbol.isEmpty) {
      _isLoading = false;
      _error = 'El símbolo de la acción no puede estar vacío.';
      notifyListeners();
      return;
    }

    _isLoading = true;
    notifyListeners();

    try {
      final nextQuote = await repository.getQuote(normalizedSymbol);
      if (_disposed || requestVersion != _requestVersion) return;

      // The UI must enforce identity even if a repository/provider is
      // replaced or returns an unexpected instrument. Non-finite numbers
      // must never be presented as verified market prices or returns.
      if (nextQuote.symbol.trim().toUpperCase() != normalizedSymbol ||
          !nextQuote.currentPrice.isFinite ||
          nextQuote.currentPrice <= 0 ||
          !nextQuote.change.isFinite ||
          !nextQuote.changePercentage.isFinite) {
        throw const FormatException('Cotización no verificable.');
      }
      _quote = nextQuote;
    } catch (_) {
      if (!_disposed && requestVersion == _requestVersion) {
        // Never expose provider errors, request URLs or private diagnostics.
        _quote = null;
        _error = 'No se pudo verificar la cotización solicitada.';
      }
    } finally {
      if (!_disposed && requestVersion == _requestVersion) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  /// Invalidate an in-flight quote before changing the presentation boundary.
  void clear() {
    if (_disposed) return;
    _requestVersion++;
    _quote = null;
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
