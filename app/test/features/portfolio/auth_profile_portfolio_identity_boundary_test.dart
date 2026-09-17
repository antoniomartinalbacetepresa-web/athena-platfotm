import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? token;

  @override
  Future<void> deleteAccessToken() async => token = null;

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String value) async => token = value;
}

AuthAccount _account(int id, String email) => AuthAccount(
      id: id,
      email: email,
      displayName: 'Owner $id',
      isActive: true,
      createdAt: DateTime.parse('2026-09-15T10:00:00Z'),
    );

http.Response _configured(double capital, String currency) => http.Response(
      jsonEncode({
        'status': 'configured',
        'data': {
          'preferences': {
            'riskTolerance': 'balanced',
            'investmentHorizon': 'medium_term',
            'baseCurrency': currency,
            'availableCapital': capital,
          }
        }
      }),
      200,
      headers: {'content-type': 'application/json'},
    );

void main() {
  test('Portfolio re-resolves Profile authority after authenticated owner changes',
      () async {
    final session = AuthSession.forTesting(_MemoryTokenStore());
    session.establish(
      accessToken: 'owner-a-token',
      account: _account(1, 'owner-a@example.com'),
    );

    final requests = <String>[];
    final service = UserPreferencesService(
      session: session,
      client: MockClient((request) async {
        final authorization = request.headers['Authorization'];
        requests.add(authorization ?? '');
        expect(request.url.path, '/api/v1/user/profile/preferences');
        if (authorization == 'Bearer owner-a-token') {
          return _configured(10000, 'EUR');
        }
        if (authorization == 'Bearer owner-b-token') {
          return _configured(2500, 'USD');
        }
        return http.Response(jsonEncode({'detail': 'unauthorized'}), 401);
      }),
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();
    expect(controller.availableCapital, 10000);
    expect(controller.currency, 'EUR');

    await session.clear();
    expect(session.isAuthenticated, isFalse);

    session.establish(
      accessToken: 'owner-b-token',
      account: _account(2, 'owner-b@example.com'),
    );
    await controller.load();

    expect(controller.availableCapital, 2500);
    expect(controller.currency, 'USD');
    expect(controller.hasVerifiedCapital, isTrue);
    expect(controller.hasVerifiedBaseCurrency, isTrue);
    expect(requests, ['Bearer owner-a-token', 'Bearer owner-b-token']);
  });

  test('Portfolio clears previous owner data when replacement session is rejected',
      () async {
    final session = AuthSession.forTesting(_MemoryTokenStore());
    session.establish(
      accessToken: 'owner-a-token',
      account: _account(1, 'owner-a@example.com'),
    );

    final service = UserPreferencesService(
      session: session,
      client: MockClient((request) async {
        if (request.headers['Authorization'] == 'Bearer owner-a-token') {
          return _configured(10000, 'EUR');
        }
        return http.Response(jsonEncode({'detail': 'expired'}), 401);
      }),
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();
    expect(controller.availableCapital, 10000);

    await session.clear();
    session.establish(
      accessToken: 'owner-b-expired-token',
      account: _account(2, 'owner-b@example.com'),
    );
    await controller.load();

    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.hasVerifiedBaseCurrency, isFalse);
    expect(controller.sessionRejected, isTrue);
    expect(session.isAuthenticated, isFalse);
  });
}
