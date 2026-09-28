import 'dart:async';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:app/features/profile/presentation/pages/profile_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;
  const storage = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');

  setUp(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, (_) async => null);
    session.clear();
  });

  tearDown(() async {
    session.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(storage, null);
  });

  AuthAccount account(int id) => AuthAccount(
        id: id,
        email: 'owner$id@example.com',
        displayName: 'Owner $id',
        isActive: true,
        createdAt: DateTime.utc(2026, 9, 1),
        updatedAt: DateTime.utc(2026, 9, 1),
      );

  testWidgets(
      'verified Profile logout removes Portfolio authority and replacement owner starts clean',
      (tester) async {
    session.establish(accessToken: 'owner-17-token', account: account(17));
    final logout = Completer<http.Response>();
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/auth/me') {
          return http.Response(
            '{"id":17,"email":"owner17@example.com","displayName":"Owner 17","isActive":true,"createdAt":"2026-09-01T00:00:00Z","updatedAt":"2026-09-01T00:00:00Z"}',
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        if (request.url.path == '/api/v1/user/preferences') {
          return http.Response('{}', 503);
        }
        if (request.url.path == '/api/v1/auth/logout') {
          expect(request.headers['Authorization'], 'Bearer owner-17-token');
          return logout.future;
        }
        return http.Response('{}', 500);
      }),
    );

    await tester.pumpWidget(MaterialApp(
      initialRoute: AppRoutes.profile,
      onGenerateRoute: (settings) => MaterialPageRoute<void>(
        settings: settings,
        builder: (_) {
          if (settings.name == AppRoutes.portfolio) {
            return const AuthenticatedPortfolioPage(
              child: SizedBox(key: Key('portfolio-cross-surface-content')),
            );
          }
          if (settings.name == AppRoutes.welcome) {
            return const Scaffold(body: Text('WELCOME AFTER LOGOUT'));
          }
          return ProfilePage(authService: auth);
        },
      ),
    ));
    await tester.pumpAndSettle();

    await tester.scrollUntilVisible(
      find.text('CERRAR SESIÓN'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('CERRAR SESIÓN'));
    await tester.pump();
    expect(session.isAuthenticated, isTrue);

    logout.complete(http.Response('', 204));
    await tester.runAsync(() async => Future<void>.delayed(Duration.zero));
    await tester.pumpAndSettle();

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(find.text('WELCOME AFTER LOGOUT'), findsOneWidget);

    await tester.pumpWidget(MaterialApp(
      home: const AuthenticatedPortfolioPage(
        child: SizedBox(key: Key('portfolio-cross-surface-content')),
      ),
    ));
    await tester.pump();

    expect(find.byKey(const Key('portfolio-authentication-required')), findsOneWidget);
    final guestSync = tester.widget<FloatingActionButton>(
      find.byKey(const Key('portfolio-authenticated-sync')),
    );
    expect(guestSync.onPressed, isNull);

    session.establish(accessToken: 'owner-18-token', account: account(18));
    await tester.pump();

    expect(session.account?.id, 18);
    expect(session.accessToken, 'owner-18-token');
    expect(find.byKey(const Key('portfolio-authentication-required')), findsNothing);
    final replacementSync = tester.widget<FloatingActionButton>(
      find.byKey(const Key('portfolio-authenticated-sync')),
    );
    expect(replacementSync.onPressed, isNotNull);

    auth.dispose();
  });
}
