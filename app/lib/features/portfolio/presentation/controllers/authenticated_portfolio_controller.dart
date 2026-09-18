import 'package:flutter/foundation.dart';

import '../../../auth/services/athena_auth_service.dart';
import '../../../market/repositories/market_repository.dart';
import '../../models/authenticated_portfolio_view_position.dart';
import '../../services/authenticated_portfolio_service.dart';

/// Presentation boundary for an authenticated owner's portfolio.
///
/// Owner holdings and cost basis always come from [AuthenticatedPortfolioService].
/// Market observations are joined in memory through [MarketRepository]. This
/// controller deliberately has no dependency on PortfolioService or the local
/// SharedPreferences-backed PortfolioRepository, so authenticated personal
/// holdings cannot silently fall back to a second local source of truth.
class AuthenticatedPortfolioController extends ChangeNotifier {
  AuthenticatedPortfolioController({
    required this._portfolioService,
    required this._marketRepository,
  });

  final AuthenticatedPortfolioService _portfolioService;
  final MarketRepository _marketRepository;

  List<AuthenticatedPortfolioViewPosition> _positions = const [];
  bool _isLoading = false;
  bool _sessionRejected = false;
  String? _error;

  List<AuthenticatedPortfolioViewPosition> get positions => _positions;
  bool get isLoading => _isLoading;
  bool get sessionRejected => _sessionRejected;
  String? get error => _error;
  bool get isEmpty => !_isLoading && !_sessionRejected && _positions.isEmpty;

  Future<void> load() async {
    if (_isLoading) return;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final valued = await _portfolioService.loadValuedPositions(
        marketRepository: _marketRepository,
      );
      _positions = List.unmodifiable(
        valued.map(AuthenticatedPortfolioViewPosition.fromValuedPosition),
      );
      _sessionRejected = false;
    } on AuthSessionRejectedException {
      _positions = const [];
      _sessionRejected = true;
      _error = null;
    } catch (_) {
      // Never retain stale owner holdings after a failed authoritative reload.
      _positions = const [];
      _sessionRejected = false;
      _error = 'No se pudo cargar la cartera autenticada con datos verificables.';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<bool> upsert({
    required String symbol,
    String? exchange,
    required double quantity,
    double? averagePurchasePrice,
  }) async {
    try {
      await _portfolioService.upsertPosition(
        symbol: symbol,
        exchange: exchange,
        quantity: quantity,
        averagePurchasePrice: averagePurchasePrice,
      );
      await load();
      return !_sessionRejected && _error == null;
    } on AuthSessionRejectedException {
      _positions = const [];
      _sessionRejected = true;
      _error = null;
      notifyListeners();
      return false;
    } catch (_) {
      _error = 'No se pudo guardar la posición autenticada.';
      notifyListeners();
      return false;
    }
  }

  Future<bool> remove(AuthenticatedPortfolioViewPosition position) async {
    try {
      await _portfolioService.deletePosition(position.id);
      await load();
      return !_sessionRejected && _error == null;
    } on AuthSessionRejectedException {
      _positions = const [];
      _sessionRejected = true;
      _error = null;
      notifyListeners();
      return false;
    } catch (_) {
      _error = 'No se pudo eliminar la posición autenticada.';
      notifyListeners();
      return false;
    }
  }
}