import 'dart:async';

import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_cloud_sync_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
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

class _DeferredSyncService extends AuthenticatedPortfolioSyncService {
  final pending = Completer<AuthenticatedPortfolioSyncReport>();
  int calls = 0;

  @override
  Future<AuthenticatedPortfolioSyncReport> syncDeclaredPositions(
    Iterable<PortfolioPosition> localPositions,
  ) {
    calls += 1;
    return pending.future;
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
  test('disposing during pending sync never publishes late success', () async {
    final service = _DeferredSyncService();
    final controller = PortfolioCloudSyncController(service: service);
    var notifications = 0;
    controller.addListener(() => notifications++);
    final pending = controller.sync([_position()]);
    expect(service.calls, 1);
    controller.dispose();
    final notificationsBeforeCompletion = notifications;

    service.pending.complete(const AuthenticatedPortfolioSyncReport(
      localPositionCount: 1,
      remotePositionCountBefore: 0,
      upsertedPositionCount: 1,
      remotePositionCountAfter: 1,
    ));
    await pending;
    expect(notifications, notificationsBeforeCompletion);
    await controller.sync([_position()]);
    expect(service.calls, 1);
  });

  test('disposing during pending sync never publishes late failure', () async {
    final service = _DeferredSyncService();
    final controller = PortfolioCloudSyncController(service: service);
    var notifications = 0;
    controller.addListener(() => notifications++);
    final pending = controller.sync([_position()]);
    controller.dispose();
    final notificationsBeforeCompletion = notifications;

    service.pending.completeError(StateError('late transport failure'));
    await pending;
    expect(notifications, notificationsBeforeCompletion);
    controller.invalidateAuthority();
    controller.clearMessage();
    expect(notifications, notificationsBeforeCompletion);
  });

  test('authority switch drops a late success and serializes pending writes', () async {
    final service = _DeferredSyncService();
    final controller = PortfolioCloudSyncController(service: service);
    final pending = controller.sync([_position()]);
    expect(controller.isSyncing, isTrue);
    controller.invalidateAuthority();
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    expect(controller.message, isNull);
    await controller.sync([_position()]);
    expect(service.calls, 1);
    service.pending.complete(const AuthenticatedPortfolioSyncReport(
      localPositionCount: 1,
      remotePositionCountBefore: 0,
      upsertedPositionCount: 1,
      remotePositionCountAfter: 1,
    ));
    await pending;
    expect(controller.isSyncing, isFalse);
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    expect(controller.message, isNull);
    controller.dispose();
  });

  test('authority switch drops a late failed sync without stale error', () async {
    final service = _DeferredSyncService();
    final controller = PortfolioCloudSyncController(service: service);
    final pending = controller.sync([_position()]);
    controller.invalidateAuthority();
    service.pending.completeError(StateError('old owner failed'));
    await pending;
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    expect(controller.message, isNull);
    expect(controller.isSyncing, isFalse);
    controller.dispose();
  });

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
    expect(controller.message, contains('precio medio de compra declarado'));
    expect(controller.message, contains('se almacena cifrado en el backend'));
    expect(controller.message, contains('No se han enviado P/L'));
    expect(controller.message, isNot(contains('no ha enviado coste de compra')));
    expect(controller.message, isNot(contains('100')));
    expect(controller.message, contains('no se han eliminado posiciones remotas'));
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

  test('owner replacement during sync is explicit and never reported as success', () async {
    final service = _FakeSyncService(
      error: const AuthenticatedPortfolioAuthorityChangedException(),
    );
    final controller = PortfolioCloudSyncController(service: service);

    await controller.sync([_position()]);

    expect(service.calls, 1);
    expect(controller.status, PortfolioCloudSyncStatus.authorityChanged);
    expect(controller.authorityChanged, isTrue);
    expect(controller.sessionRejected, isFalse);
    expect(controller.hasError, isTrue);
    expect(controller.message, contains('cuenta ATHENA cambió'));
    expect(controller.message, contains('cuenta anterior'));
    expect(controller.message, isNot(contains('Sincronización completada')));
  });
}
