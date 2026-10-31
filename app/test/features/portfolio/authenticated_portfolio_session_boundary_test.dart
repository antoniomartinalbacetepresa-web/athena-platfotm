import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_cloud_sync_controller.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_sync_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    session.clear();
  });
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

  Future<PortfolioCloudSyncController> pumpWithStatus(
    WidgetTester tester, {
    required int statusCode,
  }) async {
    session.establish(accessToken: 'owner.jwt', account: account());
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer owner.jwt');
      return http.Response('{"detail":"backend response"}', statusCode);
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
            positionsLoader: () async => [position()],
            syncController: controller,
            child: const SizedBox.expand(),
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
    await tester.pump();
    for (var frame = 0; frame < 20; frame++) {
      if (controller.status != PortfolioCloudSyncStatus.syncing) {
        break;
      }
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(
      controller.status,
      isNot(PortfolioCloudSyncStatus.syncing),
      reason: 'Portfolio sync boundary did not complete within 1 second.',
    );
    return controller;
  }

  testWidgets('401 from portfolio backend invalidates the local authenticated session',
      (tester) async {
    final controller = await pumpWithStatus(tester, statusCode: 401);
    await tester.pump();

    // The 401 still revokes the credential. The guest boundary must not
    // retain the former owner's sync status or its snackbar after revocation.
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    expect(controller.message, isNull);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
    expect(find.byKey(const Key('portfolio-authentication-required')), findsOneWidget);
    expect(find.textContaining('Tu sesión ATHENA ya no es válida'), findsNothing);

    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets('503 keeps authenticated session because revocation is not proven',
      (tester) async {
    final controller = await pumpWithStatus(tester, statusCode: 503);

    expect(controller.status, PortfolioCloudSyncStatus.failure);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'owner.jwt');
    expect(session.account?.email, 'owner@example.com');
    expect(
      find.textContaining('No se pudo sincronizar la cartera autenticada.'),
      findsOneWidget,
    );

    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  for (final status in [401, 403]) {
    test('late $status from previous owner cannot revoke replacement Portfolio session',
        () async {
      session.establish(accessToken: 'old-owner.jwt', account: account());
      final requestStarted = Completer<void>();
      final response = Completer<http.Response>();
      final client = MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer old-owner.jwt');
        requestStarted.complete();
        return response.future;
      });
      final service = AuthenticatedPortfolioService(
        baseUrl: 'http://athena.local',
        client: client,
        session: session,
      );

      final pending = service.loadPositions();
      await requestStarted.future;
      session.establish(
        accessToken: 'replacement-owner.jwt',
        account: AuthAccount(
          id: 23,
          email: 'replacement@example.com',
          displayName: 'Replacement',
          isActive: true,
          createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
          updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
        ),
      );
      response.complete(http.Response('{"detail":"revoked old token"}', status));

      await expectLater(pending, throwsA(isA<AuthSessionRejectedException>()));
      expect(session.isAuthenticated, isTrue);
      expect(session.account?.id, 23);
      expect(session.accessToken, 'replacement-owner.jwt');
      service.dispose();
    });
  }

}