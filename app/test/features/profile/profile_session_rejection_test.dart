import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/profile/presentation/pages/profile_personalization_shell.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? value;

  @override
  Future<void> deleteAccessToken() async => value = null;

  @override
  Future<String?> readAccessToken() async => value;

  @override
  Future<void> writeAccessToken(String token) async => value = token;
}

void main() {
  AuthAccount account() => AuthAccount(
        id: 17,
        email: 'profile-owner@example.com',
        displayName: 'Profile Owner',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  Map<String, dynamic> safeProjection() => {
        'schema': 'athena.user-personalization.v1',
        'fingerprint': 'a' * 64,
        'presentation': {
          'detailLevel': 'guided',
          'explanationStyle': 'plain_language',
          'riskEmphasis': 'standard',
          'horizonEmphasis': 'long_term',
          'liquidityEmphasis': 'medium',
          'objectiveFocus': 'long_term_growth',
        },
        'policy': {
          'presentationOnly': true,
          'recommendationScoringInfluence': false,
          'canonicalWeightingInfluence': false,
          'automaticLearningPromotion': false,
          'automaticTrading': false,
          'sensitiveValuesIncluded': false,
        },
      };

  test('401 is exposed as an authoritative profile session rejection', () async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'profile.jwt',
      account: account(),
    );
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient(
        (_) async => http.Response('{"detail":"Token inválido"}', 401),
      ),
    );

    await expectLater(
      service.loadPersonalization(),
      throwsA(isA<UserPreferencesSessionRejectedException>()),
    );

    // A backend 401/403 is authoritative: the service revokes both in-memory
    // authority and the durable credential before surfacing the rejection.
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
    expect(store.value, isNull);
  });

  test('503 remains a transient profile failure, not a session rejection', () async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'profile.jwt',
      account: account(),
    );
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) async => http.Response('{}', 503)),
    );

    await expectLater(service.loadPersonalization(), throwsStateError);

    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'profile.jwt');
    expect(store.value, 'profile.jwt');
  });

  testWidgets(
      'profile personalization 401 clears durable session and closes authenticated controls',
      (tester) async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'profile.jwt',
      account: account(),
    );
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient(
        (_) async => http.Response('{"detail":"Token revocado"}', 401),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ProfilePersonalizationShell(
          session: session,
          service: service,
          child: const SizedBox.expand(),
        ),
      ),
    );

    expect(find.byKey(const Key('open-profile-personalization')), findsOneWidget);
    expect(find.byKey(const Key('open-account-lifecycle')), findsOneWidget);

    await tester.tap(find.byKey(const Key('open-profile-personalization')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const Key('personalization-session-rejected')),
      findsOneWidget,
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.value, isNull);

    await tester.tap(
      find.byKey(const Key('personalization-session-rejected-close')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('open-profile-personalization')), findsNothing);
    expect(find.byKey(const Key('open-account-lifecycle')), findsNothing);
  });

  testWidgets('profile personalization 503 keeps session and supports retry',
      (tester) async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'profile.jwt',
      account: account(),
    );
    var calls = 0;
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((_) async {
        calls += 1;
        if (calls == 1) return http.Response('{}', 503);
        return http.Response(
          jsonEncode({'status': 'configured', 'data': safeProjection()}),
          200,
        );
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ProfilePersonalizationShell(
          session: session,
          service: service,
          child: const SizedBox.expand(),
        ),
      ),
    );

    await tester.tap(find.byKey(const Key('open-profile-personalization')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('personalization-error')), findsOneWidget);
    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'profile.jwt');
    expect(store.value, 'profile.jwt');

    await tester.tap(find.text('REINTENTAR'));
    await tester.pumpAndSettle();

    expect(calls, 2);
    expect(find.byKey(const Key('personalization-error')), findsNothing);
    expect(find.text('Guiado'), findsOneWidget);
    expect(session.isAuthenticated, isTrue);
  });
}
