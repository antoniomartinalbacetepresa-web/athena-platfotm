import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/profile/presentation/pages/profile_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

AuthAccount _account(int id) => AuthAccount(
      id: id,
      email: 'owner$id@example.com',
      displayName: 'Owner $id',
      isActive: true,
      createdAt: DateTime.utc(2026, 9, 1),
      updatedAt: DateTime.utc(2026, 9, 1),
    );

void main() {
  final session = AuthSession.instance;
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    session.clear();
  });
  tearDown(() => session.clear());

  testWidgets('mounted Profile immediately removes owner UI on logout and replaces it on new login',
      (tester) async {
    session.establish(accessToken: 'owner-a', account: _account(17));
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((_) async => http.Response('{}', 503)),
    );
    await tester.pumpWidget(MaterialApp(home: ProfilePage(authService: auth)));
    await tester.pumpAndSettle();
    expect(find.text('Owner 17'), findsOneWidget);
    expect(find.text('owner17@example.com'), findsOneWidget);

    session.clear();
    await tester.pump();
    expect(find.text('Perfil protegido'), findsOneWidget);
    expect(find.text('Owner 17'), findsNothing);
    expect(find.text('Preferencias protegidas'), findsNothing);

    session.establish(accessToken: 'owner-b', account: _account(23));
    await tester.pumpAndSettle();
    expect(find.text('Owner 23'), findsOneWidget);
    expect(find.text('owner23@example.com'), findsOneWidget);
    expect(find.text('Owner 17'), findsNothing);
    expect(find.text('Perfil protegido'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    auth.dispose();
  });

  testWidgets('same-token new authority rejects late old /me response in mounted Profile',
      (tester) async {
    session.establish(accessToken: 'reused-token', account: _account(17));
    final oldResponse = Completer<http.Response>();
    var calls = 0;
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/auth/me');
        expect(request.headers['Authorization'], 'Bearer reused-token');
        calls++;
        if (calls == 1) return oldResponse.future;
        return http.Response('{}', 503);
      }),
    );
    await tester.pumpWidget(MaterialApp(home: ProfilePage(authService: auth)));
    await tester.pump();
    expect(calls, 1);

    // The credential string can be reused, but the authenticated owner and
    // generation are different. Neither the old identity nor its preferences
    // may be restored by a delayed successful response.
    session.establish(accessToken: 'reused-token', account: _account(23));
    // MockClient dispatches the second request asynchronously; drain that
    // real async boundary rather than assuming a frame pump has dispatched it.
    await tester.runAsync(() async => Future<void>.delayed(Duration.zero));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Owner 23'), findsOneWidget);
    expect(find.text('Owner 17'), findsNothing);

    oldResponse.complete(http.Response(
      '{"status":"authenticated","account":{"id":17,"email":"owner17@example.com","displayName":"Owner 17","isActive":true,"createdAt":"2026-09-01T00:00:00Z","updatedAt":"2026-09-01T00:00:00Z"}}',
      200,
      headers: {'content-type': 'application/json'},
    ));
    await tester.pumpAndSettle();
    expect(session.account?.id, 23);
    expect(session.accessToken, 'reused-token');
    expect(find.text('Owner 23'), findsOneWidget);
    expect(find.text('Owner 17'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
    auth.dispose();
  });

  testWidgets('same-token same-owner renewal revalidates mounted Profile and ignores stale /me',
      (tester) async {
    session.establish(accessToken: 'reused-token', account: _account(17));
    final oldResponse = Completer<http.Response>();
    var calls = 0;
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/auth/me');
        calls++;
        if (calls == 1) return oldResponse.future;
        return http.Response('{}', 503);
      }),
    );
    await tester.pumpWidget(MaterialApp(home: ProfilePage(authService: auth)));
    await tester.pump();
    expect(calls, 1);

    // A distinct authority generation must be revalidated even if its
    // credential and owner are unchanged.
    session.establish(accessToken: 'reused-token', account: _account(17));
    final renewedVersion = session.authorityVersion;
    await tester.runAsync(() async => Future<void>.delayed(Duration.zero));
    await tester.pumpAndSettle();
    expect(calls, 2);
    expect(find.text('Owner 17'), findsOneWidget);

    oldResponse.complete(http.Response(
      '{"status":"authenticated","account":{"id":17,"email":"owner17@example.com","displayName":"Owner 17","isActive":true,"createdAt":"2026-09-01T00:00:00Z","updatedAt":"2026-09-01T00:00:00Z"}}',
      200,
      headers: {'content-type': 'application/json'},
    ));
    await tester.pumpAndSettle();
    expect(session.authorityVersion, renewedVersion);
    expect(session.account?.id, 17);
    expect(calls, 2);
    await tester.pumpWidget(const SizedBox.shrink());
    auth.dispose();
  });
}
