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
  bool get sensitiveCostBasisTransmitted => true;
}

/// Bridges the existing local portfolio UI with the authenticated owner-scoped
/// backend while persisting only the declared average purchase price as
/// sensitive cost basis. The backend encrypts that field before storage.
///
/// Deliberate safety rules:
/// - symbol, exchange, quantity and declared average purchase price are sent;
/// - current market price, capital, P/L and cost-basis dates remain local;
/// - remote positions missing locally are never deleted automatically;
/// - ownership is never supplied by the client and remains token-derived;
/// - this sync does not authorize recommendations or trading.
class AuthenticatedPortfolioSyncService {
  static const double _maxEconomicValue = 1000000000000;

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
          averagePurchasePrice: position.averagePrice,
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
      if (!position.shares.isFinite ||
          position.shares <= 0 ||
          position.shares > _maxEconomicValue) {
        throw ArgumentError.value(
          position.shares,
          'shares',
          'La cantidad declarada debe ser positiva, finita y estar dentro del límite operativo.',
        );
      }
      if (!position.averagePrice.isFinite ||
          position.averagePrice <= 0 ||
          position.averagePrice > _maxEconomicValue) {
        throw ArgumentError.value(
          position.averagePrice,
          'averagePrice',
          'El precio medio declarado debe ser positivo, finito y estar dentro del límite operativo.',
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