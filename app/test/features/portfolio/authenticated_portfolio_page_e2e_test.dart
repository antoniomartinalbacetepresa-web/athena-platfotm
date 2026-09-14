import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_cloud_sync_controller.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_sync_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;

  setUp(() => session.clear());
  tearDown(() => session.clear());

  AuthAccount account() => AuthAccount(
        id: 7,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  PortfolioPosition position() => PortfolioPosition(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        shares: 3,
        averagePrice: 123.45,
        currentPrice: 150,
        priceCurrency: 'USD',
        exchange: 'NASDAQ',
        currentPriceSourceProvider: 'test-market-source',
      );

  testWidgets(
    'authenticated sync flows from UI through bearer transport without owner fields',
    (tester) async {
      session.establish(accessToken: 'owner.jwt', account: account());
      final requests = <http.Request>[];
      var getCount = 0;
      final client = MockClient((request) async {
        requests.add(request);
        expect(request.headers['Authorization'], 'Bearer owner.jwt');
        if (request.method == 'GET') {
          getCount += 1;
          final positions = getCount == 1
              ? '[]'
              : '[{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"averagePurchasePrice":123.45,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}]';
          return http.Response(
            '{"data":{"positions":$positions,"positionCount":${getCount == 1 ? 0 : 1}}}',
            200,
          );
        }
        if (request.method == 'PUT') {
          return http.Response(
            '{"data":{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"averagePurchasePrice":123.45,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
            200,
          );
        }
        return http.Response('{}', 500);
      });
      final remote = AuthenticatedPortfolioService(
        baseUrl: 'http://athena.local',
        client: client,
        session: session,
      );
      final syncService = AuthenticatedPortfolioSyncService(remoteService: remote);
      final controller = PortfolioCloudSyncController(service: syncService);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AuthenticatedPortfolioPage(
              positionsLoader: () async => [position()],
              syncController: controller,
              child: const SizedBox.expand(),
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
      await tester.pumpAndSettle();

      expect(controller.status, PortfolioCloudSyncStatus.success);
      expect(requests.map((request) => request.method), ['GET', 'PUT', 'GET']);
      final put = requests.singleWhere((request) => request.method == 'PUT');
      expect(put.url.path, '/api/v1/user/portfolio/positions');
      final body = jsonDecode(put.body) as Map<String, dynamic>;
      expect(body, {
        'symbol': 'AAPL',
        'exchange': 'NASDAQ',
        'quantity': 3.0,
        'averagePurchasePrice': 123.45,
      });
      expect(body.containsKey('ownerUserId'), isFalse);
      expect(body.containsKey('userId'), isFalse);
      expect(body.containsKey('currentPrice'), isFalse);
      expect(body.containsKey('automaticTrading'), isFalse);
      expect(find.textContaining('Sincronización completada: 1 de 1'), findsOneWidget);

      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets('guest sync remains local and performs no network operation',
      (tester) async {
    var networkCalled = false;
    var positionsRead = false;
    final client = MockClient((request) async {
      networkCalled = true;
      return http.Response('{}', 500);
    });
    final remote = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );
    final controller = PortfolioCloudSyncController(
      service: AuthenticatedPortfolioSyncService(remoteService: remote),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AuthenticatedPortfolioPage(
            positionsLoader: () async {
              positionsRead = true;
              return [position()];
            },
            syncController: controller,
            child: const SizedBox.expand(),
          ),
        ),
      ),
    );

    await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
    await tester.pumpAndSettle();

    expect(networkCalled, isFalse);
    expect(positionsRead, isFalse);
    expect(
      find.text('Inicia sesión para sincronizar posiciones con tu cuenta ATHENA.'),
      findsOneWidget,
    );

    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
