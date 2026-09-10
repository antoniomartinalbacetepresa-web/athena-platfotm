import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/profile/models/user_preferences.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;

  setUp(() => session.clear());
  tearDown(() => session.clear());

  AuthAccount account() => AuthAccount(
        id: 9,
        email: 'profile@example.com',
        displayName: 'Profile User',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  test('guest session is rejected before profile network access', () async {
    var called = false;
    final client = MockClient((request) async {
      called = true;
      return http.Response('{}', 500);
    });
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    await expectLater(service.load(), throwsStateError);
    expect(called, isFalse);
  });

  test('load returns null when encrypted profile is not configured', () async {
    session.establish(accessToken: 'profile.jwt', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"status":"not_configured","data":null,"policy":{"sensitivePreferencesEncrypted":true}}',
        200,
      );
    });
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    final preferences = await service.load();

    expect(preferences, isNull);
    expect(captured.method, 'GET');
    expect(captured.headers['Authorization'], 'Bearer profile.jwt');
  });

  test('save sends only the validated preference contract', () async {
    session.establish(accessToken: 'profile.jwt', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        '{"status":"configured","data":{"preferences":{"riskTolerance":"balanced","investmentHorizonYears":15,"baseCurrency":"EUR","objective":"long_term_growth"},"createdAt":"2026-09-10T10:00:00Z","updatedAt":"2026-09-10T10:00:00Z"}}',
        200,
      );
    });
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );
    const input = UserPreferences(
      riskTolerance: 'balanced',
      investmentHorizonYears: 15,
      baseCurrency: 'eur',
      objective: 'long_term_growth',
    );

    final stored = await service.save(input);

    final body = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(captured.method, 'PUT');
    expect(captured.headers['Authorization'], 'Bearer profile.jwt');
    expect(body, {
      'riskTolerance': 'balanced',
      'investmentHorizonYears': 15,
      'baseCurrency': 'EUR',
      'objective': 'long_term_growth',
    });
    expect(body.containsKey('ownerUserId'), isFalse);
    expect(body.containsKey('userId'), isFalse);
    expect(stored.baseCurrency, 'EUR');
  });

  test('delete is authenticated and accepts only 204', () async {
    session.establish(accessToken: 'profile.jwt', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('', 204);
    });
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    await service.delete();

    expect(captured.method, 'DELETE');
    expect(captured.url.path, '/api/v1/user/profile/preferences');
    expect(captured.headers['Authorization'], 'Bearer profile.jwt');
  });
}
