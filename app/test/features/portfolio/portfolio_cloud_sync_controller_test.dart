import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_cloud_sync_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_sync_service.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakeSyncService extends AuthenticatedPortfolioSyncService {
  _FakeSyncService({this.error});

  Object? error;
  int calls = 0;
  List<PortfolioPosition> received = const [];

  @override
  Future<AuthenticatedPortfolioSyncReport> syncDeclaredPositions(
    Iterable<PortfolioPosition> localPositions,
  ) async {
    calls += 1;
    received = localPositions.toList(growable: false);
    if (error != null) throw error!;
    return AuthenticatedPortfolioSyncReport(
      localPositionCount: received.length,
      remotePositionCountBefore: 0,
      upsertedPositionCount: received.length,
      remotePositionCountAfter: received.length,
    );
  }
}

PortfolioPosition _position() => PortfolioPosition(
      symbol: 'AAPL',
      companyName: 'Apple',
      shares: 2,
      averagePrice: 100,
      currentPrice: 150,
      costBasisDate: DateTime.parse('2024-01-02T00:00:00Z'),
      priceCurrency: 'USD',
      exchange: 'NASDAQ',
      currentPriceSourceProvider: 'provider',
    );

void main() {
  test('empty portfolio fails closed without contacting backend', () async {
    final service = _FakeSyncService();
    final controller = PortfolioCloudSyncController(service: service);

    await controller.sync(const []);

    expect(service.calls, 0);
    expect(controller.status, PortfolioCloudSyncStatus.failure);
    expect(controller.hasError, isTrue);
    expect(controller.message, contains('No hay posiciones'));
  });

  test('successful explicit sync exposes non-destructive user message', () async {
    final service = _FakeSyncService();
    final controller = PortfolioCloudSyncController(service: service);

    await controller.sync([_position()]);

    expect(service.calls, 1);
    expect(service.received, hasLength(1));
    expect(controller.status, PortfolioCloudSyncStatus.success);
    expect(controller.message, contains('1 de 1'));
    expect(controller.message, contains('no ha enviado coste de compra'));
    expect(controller.message, contains('no ha eliminado posiciones remotas'));
  });

  test('sync failure preserves fail-closed semantics in presentation state', () async {
    final service = _FakeSyncService(error: StateError('backend unavailable'));
    final controller = PortfolioCloudSyncController(service: service);

    await controller.sync([_position()]);

    expect(service.calls, 1);
    expect(controller.status, PortfolioCloudSyncStatus.failure);
    expect(controller.hasError, isTrue);
    expect(controller.message, contains('cartera local no se ha modificado'));
    expect(controller.message, contains('no aplica cambios destructivos'));
  });
}
