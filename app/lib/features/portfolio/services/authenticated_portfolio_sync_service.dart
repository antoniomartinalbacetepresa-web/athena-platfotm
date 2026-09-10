import '../models/authenticated_portfolio_position.dart';
import '../models/portfolio_position.dart';
import 'authenticated_portfolio_service.dart';

class AuthenticatedPortfolioSyncReport {
  const AuthenticatedPortfolioSyncReport({
    required this.localPositionCount,
    required this.remotePositionCountBefore,
    required this.upsertedPositionCount,
    required this.remotePositionCountAfter,
  });

  final int localPositionCount;
  final int remotePositionCountBefore;
  final int upsertedPositionCount;
  final int remotePositionCountAfter;

  bool get destructiveChangesApplied => false;
  bool get sensitiveCostBasisTransmitted => false;
}

/// Bridges the existing local portfolio UI with the authenticated owner-scoped
/// backend without silently migrating sensitive portfolio fields.
///
/// Deliberate safety rules:
/// - only symbol, exchange and quantity are transmitted;
/// - average cost, capital, P/L and cost-basis dates remain local;
/// - remote positions missing locally are never deleted automatically;
/// - ownership is never supplied by the client and remains token-derived.
class AuthenticatedPortfolioSyncService {
  AuthenticatedPortfolioSyncService({
    AuthenticatedPortfolioService? remoteService,
  })  : _remoteService = remoteService ?? AuthenticatedPortfolioService(),
        _ownsRemoteService = remoteService == null;

  final AuthenticatedPortfolioService _remoteService;
  final bool _ownsRemoteService;

  Future<AuthenticatedPortfolioSyncReport> syncDeclaredPositions(
    Iterable<PortfolioPosition> localPositions,
  ) async {
    final positions = localPositions.toList(growable: false);
    _validateLocalPositions(positions);

    final before = await _remoteService.loadPositions();
    final synced = <AuthenticatedPortfolioPosition>[];
    for (final position in positions) {
      synced.add(
        await _remoteService.upsertPosition(
          symbol: position.symbol,
          exchange: position.exchange,
          quantity: position.shares,
        ),
      );
    }

    final after = await _remoteService.loadPositions();
    return AuthenticatedPortfolioSyncReport(
      localPositionCount: positions.length,
      remotePositionCountBefore: before.length,
      upsertedPositionCount: synced.length,
      remotePositionCountAfter: after.length,
    );
  }

  void _validateLocalPositions(List<PortfolioPosition> positions) {
    final identities = <String>{};
    for (final position in positions) {
      final symbol = position.symbol.trim().toUpperCase();
      final exchange = (position.exchange ?? '').trim().toUpperCase();
      if (symbol.isEmpty || symbol.length > 32) {
        throw ArgumentError.value(position.symbol, 'symbol', 'Símbolo no válido.');
      }
      if (!position.shares.isFinite || position.shares <= 0) {
        throw ArgumentError.value(
          position.shares,
          'shares',
          'La cantidad declarada debe ser positiva y finita.',
        );
      }
      final identity = '$symbol|$exchange';
      if (!identities.add(identity)) {
        throw StateError(
          'La cartera local contiene una posición duplicada para $symbol/$exchange.',
        );
      }
    }
  }

  void dispose() {
    if (_ownsRemoteService) _remoteService.dispose();
  }
}
