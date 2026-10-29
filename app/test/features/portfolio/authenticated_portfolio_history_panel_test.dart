import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/presentation/widgets/authenticated_portfolio_history_panel.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _hashA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _hashB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

void main() {
  final session = AuthSession.instance;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    session.clear();
    session.establish(
      accessToken: 'signed.jwt.token',
      account: AuthAccount(
        id: 7,
        email: 'user@example.com',
        displayName: 'Athena User',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      ),
    );
  });
  tearDown(() => session.clear());

  Widget harness(AuthenticatedPortfolioService service) => MaterialApp(
        home: Scaffold(
          body: AuthenticatedPortfolioHistoryPanel(service: service),
        ),
      );

  AuthenticatedPortfolioService serviceFor(http.Response response) =>
      AuthenticatedPortfolioService(
        baseUrl: 'http://athena.local',
        session: session,
        client: MockClient((request) async => response),
      );

  http.Response historyResponse(String portfolioId, int sequence) => http.Response(
        jsonEncode({
          'data': {
            'portfolioId': portfolioId,
            'asOf': '2026-09-12T06:00:00Z',
            'events': [
              {
                'sequence': sequence,
                'recordHash': _hashA,
                'eventKey': _hashB,
                'portfolioId': portfolioId,
                'eventType': 'cash_dividend',
                'occurredAt': '2026-09-12T05:00:00Z',
                'availableAt': '2026-09-12T05:01:00Z',
                'currency': 'EUR',
                'amount': 10,
                'source': 'user_portfolio',
                'sourceRef': 'dividend-$sequence',
              }
            ],
            'eventCount': 1,
            'hasMore': false,
          },
        }),
        200,
      );

  testWidgets('late 401 from previous owner cannot clear replacement session',
      (tester) async {
    final oldResponse = Completer<http.Response>();
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async {
        if (request.headers['Authorization'] == 'Bearer signed.jwt.token') {
          return oldResponse.future;
        }
        return historyResponse('primary', 22);
      }),
    );
    await tester.pumpWidget(harness(service));
    await tester.pump();
    session.establish(
      accessToken: 'replacement.jwt.token',
      account: AuthAccount(
        id: 8,
        email: 'replacement@example.com',
        displayName: 'Replacement',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-event-22')), findsOneWidget);
    oldResponse.complete(http.Response('{"detail":"Sesión caducada"}', 401));
    await tester.pumpAndSettle();
    expect(session.accessToken, 'replacement.jwt.token');
    expect(session.account?.id, 8);
    expect(find.byKey(const Key('portfolio-history-event-22')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-session-rejected')),
        findsNothing);
  });

  testWidgets('changing portfolioId ignores stale history and reloads',
      (tester) async {
    final primaryResponse = Completer<http.Response>();
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async {
        final id = request.url.queryParameters['portfolioId'];
        if (id == 'primary') return primaryResponse.future;
        return historyResponse('secondary', 33);
      }),
    );
    Widget withId(String id) => MaterialApp(
          home: Scaffold(
            body: AuthenticatedPortfolioHistoryPanel(
              service: service,
              portfolioId: id,
            ),
          ),
        );
    await tester.pumpWidget(withId('primary'));
    await tester.pump();
    await tester.pumpWidget(withId('secondary'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-event-33')), findsOneWidget);
    primaryResponse.complete(historyResponse('primary', 11));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-event-33')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-event-11')), findsNothing);
  });

  testWidgets('logout immediately removes visible owner history',
      (tester) async {
    final service = serviceFor(historyResponse('primary', 44));
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-event-44')), findsOneWidget);
    session.clear();
    await tester.pump();
    expect(find.byKey(const Key('portfolio-history-event-44')), findsNothing);
    expect(find.byKey(const Key('portfolio-history-session-rejected')),
        findsOneWidget);
  });

  testWidgets('renders authenticated ledger event and read-only disclosure',
      (tester) async {
    final service = serviceFor(http.Response(jsonEncode({'data': {'portfolioId': 'primary','asOf': '2026-09-12T06:00:00Z','events': [{'sequence': 9,'recordHash': _hashA,'eventKey': _hashB,'portfolioId': 'primary','eventType': 'trade_execution','occurredAt': '2026-09-12T05:00:00Z','availableAt': '2026-09-12T05:01:00Z','currency': 'EUR','amount': -405.5,'instrumentId': 'MSFT:XNAS','quantity': 1,'source': 'user_portfolio','sourceRef': 'trade-9'}],'eventCount': 1,'hasMore': false}}), 200));
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.text('Historial de cartera'), findsOneWidget);
    expect(find.text('Fuente: Event Ledger autenticado. Solo lectura; no envía órdenes.'), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-event-9')), findsOneWidget);
    expect(find.text('Operación ejecutada'), findsOneWidget);
    expect(find.textContaining('MSFT:XNAS'), findsOneWidget);
    expect(find.textContaining('Fuente: user_portfolio'), findsOneWidget);
    final header = tester.widget<Semantics>(find.ancestor(of: find.text('Historial de cartera'), matching: find.byType(Semantics)).first);
    expect(header.properties.header, isTrue);
    expect(header.properties.label, 'Historial de cartera autenticado');
    final disclosure = tester.widget<Semantics>(find.ancestor(of: find.text('Fuente: Event Ledger autenticado. Solo lectura; no envía órdenes.'), matching: find.byType(Semantics)).first);
    expect(disclosure.properties.label, 'Historial de solo lectura. No ejecuta operaciones ni órdenes.');
  });

  testWidgets('renders empty authenticated history without fabricating events', (tester) async {
    final service = serviceFor(http.Response(jsonEncode({'data': {'portfolioId': 'primary','asOf': '2026-09-12T06:00:00Z','events': const [],'eventCount': 0,'hasMore': false}}), 200));
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-empty')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-list')), findsNothing);
  });

  testWidgets('transient history failure preserves session and supports retry', (tester) async {
    var attempts = 0;
    final service = AuthenticatedPortfolioService(baseUrl: 'http://athena.local', session: session, client: MockClient((request) async {
      attempts += 1;
      if (attempts == 1) return http.Response('{"detail":"No se pudo leer el historial de cartera."}', 503);
      return http.Response(jsonEncode({'data': {'portfolioId': 'primary','asOf': '2026-09-12T06:00:00Z','events': const [],'eventCount': 0,'hasMore': false}}), 200);
    }));
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-error')), findsOneWidget);
    final errorSemantics = tester.widget<Semantics>(find.ancestor(of: find.byKey(const Key('portfolio-history-error')), matching: find.byType(Semantics)).first);
    expect(errorSemantics.properties.liveRegion, isTrue);
    expect(errorSemantics.properties.label, 'Error al cargar el historial de la cuenta.');
    expect(find.textContaining('No se pudo leer el historial de cartera.'), findsNothing);
    expect(find.byKey(const Key('portfolio-history-session-rejected')), findsNothing);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'signed.jwt.token');
    await tester.tap(find.byKey(const Key('portfolio-history-retry')));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.byKey(const Key('portfolio-history-empty')), findsOneWidget);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'signed.jwt.token');
  });

  testWidgets('401 history rejection clears session and does not offer retry', (tester) async {
    final service = serviceFor(http.Response('{"detail":"La sesión ya no es válida."}', 401));
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-session-rejected')), findsOneWidget);
    final rejectedSemantics = tester.widget<Semantics>(find.ancestor(of: find.byKey(const Key('portfolio-history-session-rejected')), matching: find.byType(Semantics)).first);
    expect(rejectedSemantics.properties.liveRegion, isTrue);
    expect(rejectedSemantics.properties.label, 'Sesión no válida. Inicia sesión de nuevo para consultar el historial de la cuenta.');
    expect(find.byKey(const Key('portfolio-history-retry')), findsNothing);
    expect(find.byKey(const Key('portfolio-history-error')), findsNothing);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
  });
  testWidgets('history loads older PIT events without losing the first page',
      (tester) async {
    const cursor = '2:${_hashA}:0123456789abcdef';
    var calls = 0;
    http.Response page(int sequence, String hash, bool more) =>
        http.Response(jsonEncode({
          'data': {
            'portfolioId': 'primary',
            'asOf': '2026-09-12T06:00:00Z',
            'events': [{
              'sequence': sequence,
              'recordHash': hash,
              'eventKey': _hashB,
              'portfolioId': 'primary',
              'eventType': 'cash_dividend',
              'occurredAt': '2026-09-12T0${sequence + 2}:00:00Z',
              'availableAt': '2026-09-12T0${sequence + 2}:01:00Z',
              'currency': 'EUR',
              'amount': 10,
              'source': 'user_portfolio',
              'sourceRef': 'dividend-$sequence',
            }],
            'eventCount': 1,
            'hasMore': more,
            'nextCursor': more ? cursor : null,
          },
        }), 200);
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async {
        calls++;
        if (calls == 1) {
          expect(request.url.queryParameters.containsKey('cursor'), isFalse);
          return page(2, _hashA, true);
        }
        expect(request.url.queryParameters['cursor'], cursor);
        expect(DateTime.parse(request.url.queryParameters['asOf']!).toUtc(),
            DateTime.parse('2026-09-12T06:00:00Z'));
        return page(1, _hashB, false);
      }),
    );
    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('portfolio-history-event-2')), findsOneWidget);
    await tester.tap(find.byKey(const Key('portfolio-history-load-more')));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.byKey(const Key('portfolio-history-event-2')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-event-1')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-load-more')), findsNothing);
  });

}
