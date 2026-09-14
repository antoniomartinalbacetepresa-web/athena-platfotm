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
    await tester.pumpAndSettle();
    return controller;
  }

  testWidgets('401 from portfolio backend invalidates the local authenticated session',
      (tester) async {
    final controller = await pumpWithStatus(tester, statusCode: 401);

    expect(controller.status, PortfolioCloudSyncStatus.sessionRejected);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
    expect(
      find.text(
        'Tu sesión ATHENA ya no es válida. Inicia sesión de nuevo antes de sincronizar.',
      ),
      findsOneWidget,
    );

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
}
