import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/profile/models/user_personalization.dart';
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

  Map<String, dynamic> safeProjection() => {
        'schema': 'athena.user-personalization.v1',
        'fingerprint': 'a' * 64,
        'presentation': {
          'detailLevel': 'technical',
          'explanationStyle': 'analytical',
          'riskEmphasis': 'standard',
          'horizonEmphasis': 'long_term',
          'liquidityEmphasis': 'low',
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

  test('safe backend projection parses into a presentation-only model', () {
    final value = UserPersonalization.fromJson(safeProjection());

    expect(value.schema, UserPersonalization.supportedSchema);
    expect(value.fingerprint, 'a' * 64);
    expect(value.presentation.detailLevel, 'technical');
    expect(value.presentation.explanationStyle, 'analytical');
    expect(value.presentation.horizonEmphasis, 'long_term');
  });

  test('parser rejects any recommendation or trading authority', () {
    final unsafeScoring = safeProjection();
    (unsafeScoring['policy'] as Map<String, dynamic>)[
        'recommendationScoringInfluence'] = true;
    expect(
      () => UserPersonalization.fromJson(unsafeScoring),
      throwsFormatException,
    );

    final unsafeTrading = safeProjection();
    (unsafeTrading['policy'] as Map<String, dynamic>)['automaticTrading'] = true;
    expect(
      () => UserPersonalization.fromJson(unsafeTrading),
      throwsFormatException,
    );
  });

  test('parser rejects malformed fingerprint and unknown presentation values', () {
    final malformedFingerprint = safeProjection()..['fingerprint'] = 'not-a-hash';
    expect(
      () => UserPersonalization.fromJson(malformedFingerprint),
      throwsFormatException,
    );

    final unknownDetail = safeProjection();
    (unknownDetail['presentation'] as Map<String, dynamic>)['detailLevel'] =
        'secret-mode';
    expect(
      () => UserPersonalization.fromJson(unknownDetail),
      throwsFormatException,
    );
  });

  test('authenticated personalization transport never sends owner identity', () async {
    session.establish(accessToken: 'profile.jwt', account: account());
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        jsonEncode({'status': 'configured', 'data': safeProjection()}),
        200,
      );
    });
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: client,
      session: session,
    );

    final personalization = await service.loadPersonalization();

    expect(personalization, isNotNull);
    expect(captured.method, 'GET');
    expect(captured.url.path, '/api/v1/user/profile/personalization');
    expect(captured.url.query, isEmpty);
    expect(captured.headers['Authorization'], 'Bearer profile.jwt');
    expect(captured.body, isEmpty);
  });

  test('not configured personalization is represented explicitly as null', () async {
    session.establish(accessToken: 'profile.jwt', account: account());
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: MockClient(
        (_) async => http.Response('{"status":"not_configured","data":null}', 200),
      ),
      session: session,
    );

    expect(await service.loadPersonalization(), isNull);
  });

  test('guest is rejected before personalization network access', () async {
    var called = false;
    final service = UserPreferencesService(
      baseUrl: 'http://athena.local',
      client: MockClient((_) async {
        called = true;
        return http.Response('{}', 500);
      }),
      session: session,
    );

    await expectLater(service.loadPersonalization(), throwsStateError);
    expect(called, isFalse);
  });
}
