import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/models/authenticated_portfolio_history.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const _hashA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const _hashB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

Map<String, dynamic> _event({
  int sequence = 2,
  String portfolioId = 'primary',
  String availableAt = '2026-09-12T05:00:00+00:00',
}) => {
      'sequence': sequence,
      'recordHash': _hashA,
      'eventKey': _hashB,
      'portfolioId': portfolioId,
      'eventType': 'trade_execution',
      'occurredAt': '2026-09-12T04:59:00+00:00',
      'availableAt': availableAt,
      'currency': 'EUR',
      'amount': -250.5,
      'instrumentId': 'AAPL:XNAS',
      'quantity': 1.5,
      'source': 'user_portfolio',
      'sourceRef': 'trade-42',
    };

void main() {
  final session = AuthSession.instance;

  AuthAccount account() => AuthAccount(
        id: 7,
        email: 'user@example.com',
        displayName: 'Athena User',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  setUp(() => session.clear());
  tearDown(() => session.clear());

  test('history model rejects evidence that violates PIT cutoff', () {
    expect(
      () => AuthenticatedPortfolioHistory.fromJson({
        'portfolioId': 'primary',
        'asOf': '2026-09-12T05:00:00+00:00',
        'events': [
          _event(availableAt: '2026-09-12T05:00:01+00:00'),
        ],
        'eventCount': 1,
        'hasMore': false,
      }),
      throwsFormatException,
    );
  });

  test('history model rejects mixed portfolio ids and invalid hashes', () {
    expect(
      () => AuthenticatedPortfolioHistory.fromJson({
        'portfolioId': 'primary',
        'asOf': '2026-09-12T06:00:00Z',
        'events': [_event(portfolioId: 'other')],
        'eventCount': 1,
        'hasMore': false,
      }),
      throwsFormatException,
    );

    final invalid = _event()..['recordHash'] = 'not-a-hash';
    expect(
      () => AuthenticatedPortfolioHistory.fromJson({
        'portfolioId': 'primary',
        'asOf': '2026-09-12T06:00:00Z',
        'events': [invalid],
        'eventCount': 1,
        'hasMore': false,
      }),
      throwsFormatException,
    );
  });

  test('loadHistory requires auth and never sends owner identity', () async {
    var called = false;
    final guestService = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        called = true;
        return http.Response('{}', 500);
      }),
      session: session,
    );
    await expectLater(guestService.loadHistory(), throwsStateError);
    expect(called, isFalse);

    session.establish(accessToken: 'signed.jwt.token', account: account());
    late http.Request captured;
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'data': {
              'portfolioId': 'primary',
              'asOf': '2026-09-12T06:00:00+00:00',
              'events': [_event()],
              'eventCount': 1,
              'hasMore': false,
            },
            'policy': {
              'ownerDerivedFromAuthenticatedToken': true,
              'clientSuppliedOwnerAccepted': false,
              'automaticTrading': false,
            },
          }),
          200,
        );
      }),
      session: session,
    );

    final history = await service.loadHistory(
      portfolioId: ' primary ',
      asOf: DateTime.parse('2026-09-12T08:00:00+02:00'),
      limit: 25,
    );

    expect(captured.method, 'GET');
    expect(captured.headers['Authorization'], 'Bearer signed.jwt.token');
    expect(captured.url.path, '/api/v1/user/portfolio/history');
    expect(captured.url.queryParameters['portfolioId'], 'primary');
    expect(captured.url.queryParameters['limit'], '25');
    expect(captured.url.queryParameters.containsKey('ownerUserId'), isFalse);
    expect(captured.url.queryParameters.containsKey('userId'), isFalse);
    expect(history.events, hasLength(1));
    expect(history.events.single.instrumentId, 'AAPL:XNAS');
    expect(history.events.single.quantity, 1.5);
  });

  test('loadHistory rejects invalid request bounds before network', () async {
    session.establish(accessToken: 'signed.jwt.token', account: account());
    var called = false;
    final service = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        called = true;
        return http.Response('{}', 500);
      }),
      session: session,
    );

    await expectLater(
      service.loadHistory(portfolioId: '   '),
      throwsArgumentError,
    );
    await expectLater(service.loadHistory(limit: 0), throwsArgumentError);
    await expectLater(service.loadHistory(limit: 501), throwsArgumentError);
    expect(called, isFalse);
  });
}
