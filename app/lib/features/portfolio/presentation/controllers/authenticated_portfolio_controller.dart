import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../auth/services/athena_auth_service.dart';
import '../../../auth/services/auth_session.dart';
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
    AuthSession? session,
  }) : _session = session ?? AuthSession.instance {
    _session.addListener(_onAuthorityChanged);
  }

  final AuthenticatedPortfolioService _portfolioService;
  final MarketRepository _marketRepository;
  final AuthSession _session;

  List<AuthenticatedPortfolioViewPosition> _positions = const [];
  bool _isLoading = false;
  bool _sessionRejected = false;
  String? _error;
  int _authorityGeneration = 0;

  List<AuthenticatedPortfolioViewPosition> get positions => _positions;
  bool get isLoading => _isLoading;
  bool get sessionRejected => _sessionRejected;
  String? get error => _error;
  bool get isEmpty => !_isLoading && !_sessionRejected && _positions.isEmpty;

  void _onAuthorityChanged() {
    // Owner data must disappear synchronously when authentication authority
    // changes. Any response already in flight belongs to the old generation
    // and is forbidden from repopulating this controller.
    _authorityGeneration += 1;
    _positions = const [];
    _isLoading = false;
    _sessionRejected = false;
    _error = null;
    notifyListeners();
    if (_session.isAuthenticated) {
      unawaited(load());
    }
  }

  Future<void> load() async {
    if (_isLoading) return;
    final generation = _authorityGeneration;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final valued = await _portfolioService.loadValuedPositions(
        marketRepository: _marketRepository,
      );
      if (generation != _authorityGeneration) return;
      _positions = List.unmodifiable(
        valued.map(AuthenticatedPortfolioViewPosition.fromValuedPosition),
      );
      _sessionRejected = false;
    } on AuthSessionRejectedException {
      if (generation != _authorityGeneration) return;
      _positions = const [];
      _sessionRejected = true;
      _error = null;
    } catch (_) {
      if (generation != _authorityGeneration) return;
      _positions = const [];
      _sessionRejected = false;
      _error = 'No se pudo cargar la cartera autenticada con datos verificables.';
    } finally {
      if (generation == _authorityGeneration) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  Future<bool> upsert({
    required String symbol,
    String? exchange,
    required double quantity,
    double? averagePurchasePrice,
  }) async {
    if (_sessionRejected) return false;
    final generation = _authorityGeneration;
    try {
      await _portfolioService.upsertPosition(
        symbol: symbol,
        exchange: exchange,
        quantity: quantity,
        averagePurchasePrice: averagePurchasePrice,
      );
      if (generation != _authorityGeneration) return false;
      await load();
      return generation == _authorityGeneration &&
          !_sessionRejected &&
          _error == null;
    } on AuthSessionRejectedException {
      if (generation != _authorityGeneration) return false;
      _positions = const [];
      _sessionRejected = true;
      _error = null;
      notifyListeners();
      return false;
    } catch (_) {
      if (generation != _authorityGeneration) return false;
      _error = 'No se pudo guardar la posición autenticada.';
      notifyListeners();
      return false;
    }
  }

  Future<bool> remove(AuthenticatedPortfolioViewPosition position) async {
    if (_sessionRejected) return false;
    final generation = _authorityGeneration;
    try {
      await _portfolioService.deletePosition(position.serverPositionId);
      if (generation != _authorityGeneration) return false;
      await load();
      return generation == _authorityGeneration &&
          !_sessionRejected &&
          _error == null;
    } on AuthSessionRejectedException {
      if (generation != _authorityGeneration) return false;
      _positions = const [];
      _sessionRejected = true;
      _error = null;
      notifyListeners();
      return false;
    } catch (_) {
      if (generation != _authorityGeneration) return false;
      _error = 'No se pudo eliminar la posición autenticada.';
      notifyListeners();
      return false;
    }
  }

  /// Direct summation is safe only for a single declared quote currency.
  /// Mixed/unknown currencies must be delegated to ATHENA's verified FX path.
  String? get directlyComparableCurrency =>
      AuthenticatedPortfolioViewPosition.commonCurrency(_positions);

  double? get directlyComparableCurrentValue {
    if (_positions.isEmpty || directlyComparableCurrency == null) return null;
    return _positions.fold<double>(
      0,
      (total, position) => total + position.currentValue,
    );
  }

  double? get directlyComparableInvestedValue {
    if (_positions.isEmpty || directlyComparableCurrency == null) return null;
    var total = 0.0;
    for (final position in _positions) {
      final invested = position.investedValue;
      if (invested == null) return null;
      total += invested;
    }
    return total;
  }

  @override
  void dispose() {
    _session.removeListener(_onAuthorityChanged);
    super.dispose();
  }
}
