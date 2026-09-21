import 'dart:async';
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

  test('owner replacement clears old capital synchronously and reloads only the new owner', () async {
    final auth = session();
    final ownerA = Completer<http.Response>();
    final service = UserPreferencesService(
      client: MockClient((request) {
        final token = request.headers['Authorization'];
        if (token == 'Bearer token') return ownerA.future;
        if (token == 'Bearer token-b') {
          return Future.value(configured(capital: 40000, currency: 'USD'));
        }
        return Future.value(http.Response('{}', 401));
      }),
      session: auth,
    );
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: service,
      session: auth,
    );

    final loadA = controller.load();
    await Future<void>.delayed(Duration.zero);
    expect(controller.isLoading, isTrue);

    auth.establish(
      accessToken: 'token-b',
      account: AuthAccount(
        id: 10,
        email: 'owner-b@example.com',
        displayName: 'Owner B',
        isActive: true,
        createdAt: DateTime.parse('2026-09-16T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-16T10:00:00Z'),
      ),
    );

    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);

    expect(controller.availableCapital, 40000);
    expect(controller.currency, 'USD');
    expect(controller.hasVerifiedCapital, isTrue);

    ownerA.complete(configured(capital: 12500, currency: 'EUR'));
    await loadA;

    expect(controller.availableCapital, 40000);
    expect(controller.currency, 'USD');
    expect(controller.error, isNull);
    controller.dispose();
    service.dispose();
  });

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
        updatedAt: DateTime.parse('2026-09-15T10:00:00Z'),
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
              'investmentHorizonYears': 10,
              'objective': 'balanced_growth',
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
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isTrue);
    expect(controller.hasVerifiedBaseCurrency, isTrue);
    expect(controller.availableCapital, 12500);
    expect(controller.currency, 'EUR');
    expect(controller.error, isNull);
    expect(controller.sessionRejected, isFalse);
  });

  test('verified Profile base currency remains available when capital is unset', () async {
    final service = UserPreferencesService(
      client: MockClient((request) async => configured(capital: null, currency: 'usd')),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.hasVerifiedBaseCurrency, isTrue);
    expect(controller.currency, 'USD');
    expect(controller.error, isNull);
    expect(controller.sessionRejected, isFalse);
  });

  test('invalid Profile base currency fails closed even when capital is unset', () async {
    final service = UserPreferencesService(
      client: MockClient((request) async => configured(capital: null, currency: 'US')),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.hasVerifiedBaseCurrency, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.error, isNotNull);
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
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.hasVerifiedBaseCurrency, isFalse);
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
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isTrue);
    expect(controller.hasVerifiedBaseCurrency, isTrue);
    await controller.load();
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.hasVerifiedBaseCurrency, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.sessionRejected, isTrue);
    expect(controller.error, isNull);
    expect(auth.isAuthenticated, isFalse);
  });

  test('authoritative failure removes previously verified capital and currency', () async {
    var calls = 0;
    final service = UserPreferencesService(
      client: MockClient((request) async {
        calls += 1;
        if (calls == 1) return configured();
        return http.Response(jsonEncode({'detail': 'temporary'}), 503);
      }),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);
    await controller.load();
    expect(controller.hasVerifiedCapital, isTrue);
    expect(controller.hasVerifiedBaseCurrency, isTrue);
    await controller.load();
    expect(controller.hasVerifiedCapital, isFalse);
    expect(controller.hasVerifiedBaseCurrency, isFalse);
    expect(controller.availableCapital, isNull);
    expect(controller.currency, isNull);
    expect(controller.sessionRejected, isFalse);
    expect(controller.error, isNotNull);
  });

  test('older overlapping load cannot overwrite newer verified capital', () async {
    final first = Completer<http.Response>();
    var calls = 0;
    final service = UserPreferencesService(
      client: MockClient((request) {
        calls += 1;
        if (calls == 1) return first.future;
        return Future.value(configured(capital: 25000, currency: 'USD'));
      }),
      session: session(),
    );
    final controller = AuthenticatedPortfolioCapitalController(preferencesService: service);

    final olderLoad = controller.load();
    await Future<void>.delayed(Duration.zero);
    await controller.load();
    expect(controller.availableCapital, 25000);
    expect(controller.currency, 'USD');

    first.complete(configured(capital: 12500, currency: 'EUR'));
    await olderLoad;

    expect(controller.availableCapital, 25000);
    expect(controller.currency, 'USD');
    expect(controller.error, isNull);
    expect(controller.isLoading, isFalse);
  });
}
