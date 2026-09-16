import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _TokenStore implements AuthTokenStore {
  @override
  Future<void> deleteAccessToken() async {}

  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<void> writeAccessToken(String token) async {}
}

void main() {
  AuthSession session() {
    final value = AuthSession.forTesting(_TokenStore());
    value.establish(
      accessToken: 'token',
      account: AuthAccount(
        id: 9,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: true,
        createdAt: DateTime.parse('2026-09-15T10:00:00Z'),
      ),
    );
    return value;
  }

  http.Response configured({double? capital = 12500, String currency = 'EUR'}) =>
      http.Response(
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

  test('loads available capital only from authenticated Profile preferences', () async {
    final auth = session();
    final service = UserPreferencesService(
      client: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer token');
        expect(request.url.path, '/api/v1/user/profile/preferences');
        return configured();
      }),
      session: auth,
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();

    expect(controller.hasVerifiedCapital, isTrue);
    expect(controller.availableCapital, 12500);
    expect(controller.currency, 'EUR');
    expect(controller.error, isNull);
    expect(controller.sessionRejected, isFalse);
  });

  test('not configured Profile never manufactures capital or currency', () async {
    final service = UserPreferencesService(
      client: MockClient((request) async => http.Response(
            jsonEncode({'status': 'not_configured'}),
            200,
            headers: {'content-type': 'application/json'},
          )),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();

    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.error, isNull);
  });

  test('401 clears capital and enters explicit rejected state', () async {
    var calls = 0;
    final auth = session();
    final service = UserPreferencesService(
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return configured();
        return http.Response(jsonEncode({'detail': 'expired'}), 401);
      }),
      session: auth,
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();
    expect(controller.hasVerifiedCapital, isTrue);

    await controller.load();

    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.sessionRejected, isTrue);
    expect(controller.error, isNull);
    expect(auth.isAuthenticated, isFalse);
  });

  test('authoritative failure removes previously verified capital', () async {
    var calls = 0;
    final service = UserPreferencesService(
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return configured();
        return http.Response(jsonEncode({'detail': 'temporary'}), 503);
      }),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
    );

    await controller.load();
    expect(controller.hasVerifiedCapital, isTrue);

    await controller.load();

    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.sessionRejected, isFalse);
    expect(controller.error, isNotNull);
  });
}
