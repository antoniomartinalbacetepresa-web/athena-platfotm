import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import 'package:app/features/portfolio/presentation/widgets/authenticated_portfolio_capital_view.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter/material.dart';
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

AuthSession _session() {
  final session = AuthSession.forTesting(_TokenStore());
  session.establish(
    accessToken: 'token',
    account: AuthAccount(
      id: 17,
      email: 'owner@example.com',
      displayName: 'Owner',
      isActive: true,
      createdAt: DateTime.parse('2026-09-15T10:00:00Z'),
      updatedAt: DateTime.parse('2026-09-15T10:00:00Z'),
    ),
  );
  return session;
}

http.Response _configured() => http.Response(
      jsonEncode({
        'status': 'configured',
        'data': {
          'preferences': {
            'riskTolerance': 'balanced',
            'investmentHorizon': 'medium_term',
            'baseCurrency': 'EUR',
            'availableCapital': 12345.67,
          }
        }
      }),
      200,
      headers: {'content-type': 'application/json'},
    );

void main() {
  testWidgets('shows verified Profile capital with its declared currency', (tester) async {
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: UserPreferencesService(
        client: MockClient((_) async => _configured()),
        session: _session(),
      ),
    );
    await controller.load();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioCapitalView(controller: controller, onRetry: controller.load))));
    expect(find.textContaining('12'), findsWidgets);
    expect(find.textContaining('EUR'), findsWidgets);
    expect(find.textContaining('Profile'), findsWidgets);
  });

  testWidgets('401 removes a previously visible capital amount', (tester) async {
    var calls = 0;
    final auth = _session();
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: UserPreferencesService(
        client: MockClient((_) async {
          calls += 1;
          if (calls == 1) return _configured();
          return http.Response(jsonEncode({'detail': 'expired'}), 401);
        }),
        session: auth,
      ),
    );
    await controller.load();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioCapitalView(controller: controller, onRetry: controller.load))));
    expect(find.textContaining('12'), findsWidgets);
    await controller.load();
    await tester.pump();
    expect(find.textContaining('12'), findsNothing);
    expect(find.textContaining('sesión'), findsWidgets);
    expect(auth.isAuthenticated, isFalse);
  });

  testWidgets('503 removes stale capital instead of presenting it as current', (tester) async {
    var calls = 0;
    final controller = AuthenticatedPortfolioCapitalController(
      preferencesService: UserPreferencesService(
        client: MockClient((_) async {
          calls += 1;
          if (calls == 1) return _configured();
          return http.Response(jsonEncode({'detail': 'temporary'}), 503);
        }),
        session: _session(),
      ),
    );
    await controller.load();
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: AuthenticatedPortfolioCapitalView(controller: controller, onRetry: controller.load))));
    expect(find.textContaining('12'), findsWidgets);
    await controller.load();
    await tester.pump();
    expect(find.textContaining('12'), findsNothing);
    expect(find.textContaining('No se pudo verificar'), findsWidgets);
  });
}
