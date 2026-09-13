import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/profile/presentation/pages/profile_personalization_shell.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

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
}
