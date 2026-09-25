import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
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

  AuthAccount account() => AuthAccount(id: 7, email: 'owner@example.com', displayName: 'Owner', isActive: true, createdAt: DateTime.parse('2026-09-10T10:00:00Z'), updatedAt: DateTime.parse('2026-09-10T10:00:00Z'));
  PortfolioPosition position() => PortfolioPosition(symbol: 'AAPL', companyName: 'Apple Inc.', shares: 3, averagePrice: 123.45, currentPrice: 150, priceCurrency: 'USD', exchange: 'NASDAQ', currentPriceSourceProvider: 'test-market-source');


  testWidgets('portfolio exposes accessible heading and presentation-only authority boundary', (tester) async {
    session.establish(accessToken: 'owner-token', account: account());

    await tester.pumpWidget(
      const MaterialApp(home: AuthenticatedPortfolioPage()),
    );
    await tester.pump();

    expect(find.text('MI CARTERA'), findsOneWidget);
    final semantics = tester.widget<Semantics>(
      find.ancestor(
        of: find.text('MI CARTERA'),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(semantics.properties.header, isTrue);
    expect(find.textContaining('no ejecuta órdenes'), findsOneWidget);
    expect(
      find.textContaining('no modifica automáticamente recomendaciones'),
      findsOneWidget,
    );
    expect(find.textContaining('pesos'), findsOneWidget);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('authenticated sync flows from UI through bearer transport without owner fields', (tester) async {
    session.establish(accessToken: 'owner-token', account: account());
    final requests = <http.Request>[];
    var getCount = 0;
    final client = MockClient((request) async {
      requests.add(request);
      expect(request.headers['Authorization'], 'Bearer owner-token');
      if (request.method == 'GET') {
        getCount += 1;
        final positions = getCount == 1 ? '[]' : '[{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"averagePurchasePrice":123.45,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}]';
        return http.Response('{"data":{"positions":$positions,"positionCount":${getCount == 1 ? 0 : 1}}}', 200);
      }
      if (request.method == 'PUT') return http.Response('{"data":{"id":9,"symbol":"AAPL","exchange":"NASDAQ","quantity":3.0,"averagePurchasePrice":123.45,"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}', 200);
      return http.Response('{}', 500);
    });
    final remote = AuthenticatedPortfolioService(baseUrl: 'http://athena.local', client: client, session: session);
    final controller = PortfolioCloudSyncController(service: AuthenticatedPortfolioSyncService(remoteService: remote));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioPage(positionsLoader: () async => [position()], syncController: controller, child: const SizedBox.expand()))));
    await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
    await tester.pumpAndSettle();
    expect(controller.status, PortfolioCloudSyncStatus.success);
    expect(requests.map((request) => request.method), ['GET', 'PUT', 'GET']);
    final put = requests.singleWhere((request) => request.method == 'PUT');
    expect(put.url.path, '/api/v1/user/portfolio/positions');
    final body = jsonDecode(put.body) as Map<String, dynamic>;
    expect(body, {'symbol': 'AAPL', 'exchange': 'NASDAQ', 'quantity': 3.0, 'averagePurchasePrice': 123.45});
    expect(body.containsKey('ownerUserId'), isFalse);
    expect(body.containsKey('userId'), isFalse);
    expect(body.containsKey('currentPrice'), isFalse);
    expect(body.containsKey('automaticTrading'), isFalse);
    expect(find.textContaining('Sincronización completada: 1 de 1'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets('owner replacement while local sync snapshot loads sends no data', (tester) async {
    session.establish(accessToken: 'owner-a-token', account: account());
    final localSnapshot = Completer<List<PortfolioPosition>>();
    var networkCalled = false;
    final remote = AuthenticatedPortfolioService(baseUrl: 'http://athena.local', session: session, client: MockClient((request) async { networkCalled = true; return http.Response('{}', 500); }));
    final controller = PortfolioCloudSyncController(service: AuthenticatedPortfolioSyncService(remoteService: remote));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioPage(positionsLoader: () => localSnapshot.future, syncController: controller, child: const SizedBox.expand()))));
    await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
    await tester.pump();
    session.establish(accessToken: 'owner-b-token', account: AuthAccount(id: 8, email: 'replacement@example.com', displayName: 'Replacement', isActive: true, createdAt: DateTime.parse('2026-09-21T10:00:00Z'), updatedAt: DateTime.parse('2026-09-21T10:00:00Z')));
    localSnapshot.complete([position()]);
    await tester.pumpAndSettle();
    expect(networkCalled, isFalse);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'owner-b-token');
    expect(session.account?.id, 8);
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    expect(find.textContaining('No se ha enviado ningún dato'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    remote.dispose();
  });

  testWidgets('guest account controls are disabled and perform no local or network work', (tester) async {
    var networkCalled = false;
    var positionsRead = false;
    final client = MockClient((request) async { networkCalled = true; return http.Response('{}', 500); });
    final remote = AuthenticatedPortfolioService(baseUrl: 'http://athena.local', client: client, session: session);
    final controller = PortfolioCloudSyncController(service: AuthenticatedPortfolioSyncService(remoteService: remote));
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioPage(positionsLoader: () async { positionsRead = true; return [position()]; }, syncController: controller, child: const SizedBox.expand()))));
    final syncButton = tester.widget<FloatingActionButton>(find.byKey(const Key('portfolio-authenticated-sync')));
    final historyButton = tester.widget<FloatingActionButton>(find.byKey(const Key('portfolio-authenticated-history')));
    expect(syncButton.onPressed, isNull);
    expect(historyButton.onPressed, isNull);
    expect(find.byKey(const Key('portfolio-authentication-required')), findsOneWidget);
    expect(networkCalled, isFalse);
    expect(positionsRead, isFalse);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets('history 401 invalidates session and parent disables all account controls after close', (tester) async {
    session.establish(accessToken: 'expired-test-token', account: account());
    var historyCalls = 0;
    final historyService = AuthenticatedPortfolioService(baseUrl: 'http://athena.local', session: session, client: MockClient((request) async {
      historyCalls += 1;
      expect(request.method, 'GET');
      expect(request.url.path, '/api/v1/user/portfolio/history');
      expect(request.headers['Authorization'], 'Bearer expired-test-token');
      return http.Response('{"detail":"session rejected"}', 401);
    }));
    final controller = PortfolioCloudSyncController();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioPage(historyService: historyService, syncController: controller, child: const SizedBox.expand()))));
    expect(session.isAuthenticated, isTrue);
    await tester.tap(find.byKey(const Key('portfolio-authenticated-history')));
    await tester.pumpAndSettle();
    expect(historyCalls, 1);
    expect(find.byKey(const Key('portfolio-history-session-rejected')), findsOneWidget);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    await tester.tap(find.byKey(const Key('portfolio-history-session-rejected-close')));
    await tester.pumpAndSettle();
    final syncButton = tester.widget<FloatingActionButton>(find.byKey(const Key('portfolio-authenticated-sync')));
    final historyButton = tester.widget<FloatingActionButton>(find.byKey(const Key('portfolio-authenticated-history')));
    expect(syncButton.onPressed, isNull);
    expect(historyButton.onPressed, isNull);
    expect(find.byKey(const Key('portfolio-authentication-required')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
    historyService.dispose();
  });

  testWidgets('login while Portfolio is mounted initializes the authenticated boundary', (tester) async {
    const authenticatedSubtitle = 'Posiciones personales protegidas por tu cuenta ATHENA';
    await tester.pumpWidget(const MaterialApp(home: AuthenticatedPortfolioPage()));
    expect(find.text(authenticatedSubtitle), findsNothing);

    session.establish(accessToken: 'owner-token', account: account());
    await tester.pump();

    expect(find.text(authenticatedSubtitle), findsOneWidget);
    expect(find.text('No se pudo inicializar la cartera autenticada.'), findsNothing);

    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('logout disposes owner boundary and relogin rebuilds it cleanly', (tester) async {
    const authenticatedSubtitle = 'Posiciones personales protegidas por tu cuenta ATHENA';
    session.establish(accessToken: 'owner-a-token', account: account());
    await tester.pumpWidget(const MaterialApp(home: AuthenticatedPortfolioPage()));
    expect(find.text(authenticatedSubtitle), findsOneWidget);

    session.clear();
    await tester.pump();
    expect(find.text(authenticatedSubtitle), findsNothing);

    session.establish(
      accessToken: 'owner-b-token',
      account: AuthAccount(
        id: 8,
        email: 'replacement@example.com',
        displayName: 'Replacement',
        isActive: true,
        createdAt: DateTime.parse('2026-09-21T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-21T10:00:00Z'),
      ),
    );
    await tester.pump();

    expect(find.text(authenticatedSubtitle), findsOneWidget);
    expect(find.text('No se pudo inicializar la cartera autenticada.'), findsNothing);
    expect(session.account?.id, 8);
    expect(session.accessToken, 'owner-b-token');

    await tester.pumpWidget(const SizedBox());
  });
}
