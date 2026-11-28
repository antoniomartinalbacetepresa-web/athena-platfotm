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
  testWidgets('rejected protected personalization announces invalid session and clears authority', (tester) async {
    final store = _MemoryTokenStore();
    final session = AuthSession.forTesting(store);
    final account = AuthAccount(
      id: 7,
      email: 'owner@example.com',
      displayName: 'Owner',
      isActive: true,
      createdAt: DateTime.parse('2026-09-10T10:00:00Z'),
      updatedAt: DateTime.parse('2026-09-10T10:00:00Z'),
    );
    await session.establishPersisted(accessToken: 'revoked-owner.jwt', account: account);
    final service = UserPreferencesService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((request) async {
        expect(request.headers['Authorization'], 'Bearer revoked-owner.jwt');
        return http.Response(jsonEncode({'detail': 'revoked'}), 401);
      }),
    );

    await tester.pumpWidget(MaterialApp(
      home: ProfilePersonalizationSheet(service: service, session: session),
    ));
    await tester.pumpAndSettle();

    final rejectedText = find.byKey(const Key('personalization-session-rejected'));
    expect(rejectedText, findsOneWidget);
    final semantics = tester.widget<Semantics>(
      find.ancestor(of: rejectedText, matching: find.byType(Semantics)).first,
    );
    expect(semantics.properties.liveRegion, isTrue);
    expect(
      semantics.properties.label,
      'Sesión no válida. Inicia sesión de nuevo para consultar la personalización protegida.',
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.value, isNull);
  });
}
