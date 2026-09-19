import 'dart:convert';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
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
  final session = AuthSession.instance;

  setUp(() => session.clear());
  tearDown(() => session.clear());

  AuthAccount account() => AuthAccount(
        id: 7,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: true,
        createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
        updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
      );

  Map<String, dynamic> projection() => {
        'schema': 'athena.user-personalization.v1',
        'fingerprint': 'c' * 64,
        'presentation': {
          'detailLevel': 'guided',
          'explanationStyle': 'plain_language',
          'riskEmphasis': 'high',
          'horizonEmphasis': 'short_term',
          'liquidityEmphasis': 'high',
          'objectiveFocus': 'capital_preservation',
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

  testWidgets('guest profile does not expose personalization entry point',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: ProfilePersonalizationShell(child: SizedBox()),
      ),
    );

    expect(find.byKey(const Key('open-profile-personalization')), findsNothing);
  });

  testWidgets('authenticated profile consumes protected projection on demand',
      (tester) async {
    session.establish(accessToken: 'owner.jwt', account: account());
    late http.Request captured;
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({'status': 'configured', 'data': projection()}),
          200,
        );
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ProfilePersonalizationShell(
          service: service,
          session: session,
          child: const SizedBox.expand(),
        ),
      ),
    );

    expect(find.byKey(const Key('open-profile-personalization')), findsOneWidget);
    await tester.tap(find.byKey(const Key('open-profile-personalization')));
    await tester.pumpAndSettle();

    expect(captured.method, 'GET');
    expect(captured.url.path, '/api/v1/user/profile/personalization');
    expect(captured.headers['Authorization'], 'Bearer owner.jwt');
    expect(find.byKey(const Key('user-personalization-panel')), findsOneWidget);
    expect(find.text('Guiado'), findsOneWidget);
    expect(find.text('Lenguaje claro'), findsOneWidget);
    expect(
      find.byKey(const Key('personalization-presentation-only-note')),
      findsOneWidget,
    );
  });

  testWidgets('invalid backend policy fails closed in the profile surface',
      (tester) async {
    session.establish(accessToken: 'owner.jwt', account: account());
    final unsafe = projection();
    (unsafe['policy'] as Map<String, dynamic>)['canonicalWeightingInfluence'] =
        true;
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'status': 'configured', 'data': unsafe}),
          200,
        ),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ProfilePersonalizationShell(
          service: service,
          session: session,
          child: const SizedBox.expand(),
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('open-profile-personalization')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('personalization-error')), findsOneWidget);
    expect(find.text('Guiado'), findsNothing);
    expect(find.textContaining('weight'), findsNothing);
  });

  testWidgets('protected Profile rejection clears authority and returns to welcome',
      (tester) async {
    final store = _MemoryTokenStore();
    final lifecycleSession = AuthSession.forTesting(store);
    await lifecycleSession.establishPersisted(
      accessToken: 'revoked-owner.jwt',
      account: account(),
    );
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: lifecycleSession,
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/user/profile/personalization');
        expect(request.headers['Authorization'], 'Bearer revoked-owner.jwt');
        return http.Response(jsonEncode({'detail': 'revoked'}), 401);
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        initialRoute: '/profile-test',
        routes: {
          AppRoutes.welcome: (_) => const Scaffold(body: Text('WELCOME')),
          '/profile-test': (_) => ProfilePersonalizationShell(
                service: service,
                session: lifecycleSession,
                child: const SizedBox.expand(),
              ),
        },
      ),
    );

    await tester.tap(find.byKey(const Key('open-profile-personalization')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const Key('personalization-session-rejected')),
      findsOneWidget,
    );
    expect(lifecycleSession.isAuthenticated, isFalse);
    expect(lifecycleSession.accessToken, isNull);
    expect(store.value, isNull);

    await tester.tap(
      find.byKey(const Key('personalization-session-rejected-close')),
    );
    await tester.pumpAndSettle();

    expect(find.text('WELCOME'), findsOneWidget);
    expect(find.byKey(const Key('open-profile-personalization')), findsNothing);
    expect(find.byKey(const Key('open-account-lifecycle')), findsNothing);
  });

  testWidgets(
      'account closure runs authenticated transport, clears persisted session and returns to welcome',
      (tester) async {
    final store = _MemoryTokenStore();
    final lifecycleSession = AuthSession.forTesting(store);
    await lifecycleSession.establishPersisted(
      accessToken: 'owner.jwt',
      account: account(),
    );
    late http.Request captured;
    final authService = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        captured = request;
        return http.Response('', 204);
      }),
    );

    await tester.pumpWidget(
      MaterialApp(
        initialRoute: '/profile-test',
        routes: {
          AppRoutes.welcome: (_) => const Scaffold(body: Text('WELCOME')),
          '/profile-test': (_) => ProfilePersonalizationShell(
                session: lifecycleSession,
                accountLifecycleAuthService: authService,
                child: const SizedBox.expand(),
              ),
        },
      ),
    );

    await tester.tap(find.byKey(const Key('open-account-lifecycle')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('account-closure-panel')), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      'test-current-passphrase',
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    await tester.tap(find.byKey(const Key('account-closure-submit')));
    await tester.pumpAndSettle();

    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/close-account');
    expect(captured.headers['Authorization'], 'Bearer owner.jwt');
    expect(
      (jsonDecode(captured.body) as Map<String, dynamic>)['currentPassword'],
      'test-current-passphrase',
    );
    expect(lifecycleSession.isAuthenticated, isFalse);
    expect(lifecycleSession.accessToken, isNull);
    expect(store.value, isNull);
    expect(find.text('WELCOME'), findsOneWidget);
  });

  testWidgets(
      'rejected account closure keeps session, durable token and destructive sheet open',
      (tester) async {
    final store = _MemoryTokenStore();
    final lifecycleSession = AuthSession.forTesting(store);
    await lifecycleSession.establishPersisted(
      accessToken: 'owner.jwt',
      account: account(),
    );
    final authService = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async => http.Response('{}', 401)),
    );

    await tester.pumpWidget(
      MaterialApp(
        initialRoute: '/profile-test',
        routes: {
          AppRoutes.welcome: (_) => const Scaffold(body: Text('WELCOME')),
          '/profile-test': (_) => ProfilePersonalizationShell(
                session: lifecycleSession,
                accountLifecycleAuthService: authService,
                child: const SizedBox.expand(),
              ),
        },
      ),
    );

    await tester.tap(find.byKey(const Key('open-account-lifecycle')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      'wrong-test-passphrase',
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    await tester.tap(find.byKey(const Key('account-closure-submit')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('account-closure-error')), findsOneWidget);
    expect(find.byKey(const Key('account-closure-panel')), findsOneWidget);
    expect(lifecycleSession.isAuthenticated, isTrue);
    expect(lifecycleSession.accessToken, 'owner.jwt');
    expect(store.value, 'owner.jwt');
    expect(find.text('WELCOME'), findsNothing);
  });
}