import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/presentation/widgets/authenticated_portfolio_history_panel.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _hashA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _hashB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

void main() {
  final session = AuthSession.instance;

  setUp(() {
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

  testWidgets('renders authenticated ledger event and read-only disclosure',
      (tester) async {
    final service = serviceFor(
      http.Response(
        jsonEncode({
          'data': {
            'portfolioId': 'primary',
            'asOf': '2026-09-12T06:00:00Z',
            'events': [
              {
                'sequence': 9,
                'recordHash': _hashA,
                'eventKey': _hashB,
                'portfolioId': 'primary',
                'eventType': 'trade_execution',
                'occurredAt': '2026-09-12T05:00:00Z',
                'availableAt': '2026-09-12T05:01:00Z',
                'currency': 'EUR',
                'amount': -405.5,
                'instrumentId': 'MSFT:XNAS',
                'quantity': 1,
                'source': 'user_portfolio',
                'sourceRef': 'trade-9',
              },
            ],
            'eventCount': 1,
            'hasMore': false,
          },
        }),
        200,
      ),
    );

    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();

    expect(find.text('Historial de cartera'), findsOneWidget);
    expect(
      find.text('Fuente: Event Ledger autenticado. Solo lectura; no envía órdenes.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('portfolio-history-event-9')), findsOneWidget);
    expect(find.text('Operación ejecutada'), findsOneWidget);
    expect(find.textContaining('MSFT:XNAS'), findsOneWidget);
    expect(find.textContaining('Fuente: user_portfolio'), findsOneWidget);
  });

  testWidgets('renders empty authenticated history without fabricating events',
      (tester) async {
    final service = serviceFor(
      http.Response(
        jsonEncode({
          'data': {
            'portfolioId': 'primary',
            'asOf': '2026-09-12T06:00:00Z',
            'events': const [],
            'eventCount': 0,
            'hasMore': false,
          },
        }),
        200,
      ),
    );

    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('portfolio-history-empty')), findsOneWidget);
    expect(find.byKey(const Key('portfolio-history-list')), findsNothing);
  });

  testWidgets('shows safe error state and supports retry', (tester) async {
    var attempts = 0;
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async {
        attempts += 1;
        if (attempts == 1) {
          return http.Response(
            '{"detail":"No se pudo leer el historial de cartera."}',
            503,
          );
        }
        return http.Response(
          jsonEncode({
            'data': {
              'portfolioId': 'primary',
              'asOf': '2026-09-12T06:00:00Z',
              'events': const [],
              'eventCount': 0,
              'hasMore': false,
            },
          }),
          200,
        );
      }),
    );

    await tester.pumpWidget(harness(service));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('portfolio-history-error')), findsOneWidget);
    expect(find.textContaining('No se pudo leer el historial de cartera.'), findsNothing);

    await tester.tap(find.byKey(const Key('portfolio-history-retry')));
    await tester.pumpAndSettle();

    expect(attempts, 2);
    expect(find.byKey(const Key('portfolio-history-empty')), findsOneWidget);
  });
}
