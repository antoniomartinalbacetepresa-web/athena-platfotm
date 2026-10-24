import 'dart:async';

import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/profile/presentation/pages/profile_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;
  const secureStorageChannel = MethodChannel(
    'plugins.it_nomads.com/flutter_secure_storage',
  );

  setUp(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(secureStorageChannel, (_) async => null);
    session.clear();
  });
  tearDown(() async {
    session.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(secureStorageChannel, null);
  });

  AuthAccount account() => AuthAccount(
        id: 17,
        email: 'profile-owner@example.com',
        displayName: 'Profile Owner',
        isActive: true,
        createdAt: DateTime.utc(2026, 9, 1),
        updatedAt: DateTime.utc(2026, 9, 1),
      );

  Widget appFor(AthenaAuthService auth) {
    return MaterialApp(
      initialRoute: AppRoutes.profile,
      onGenerateRoute: (settings) {
        if (settings.name == AppRoutes.welcome) {
          return MaterialPageRoute<void>(
            settings: settings,
            builder: (_) => const Scaffold(
              body: Text('WELCOME AFTER VERIFIED LOGOUT'),
            ),
          );
        }
        return MaterialPageRoute<void>(
          settings: settings,
          builder: (_) => ProfilePage(authService: auth),
        );
      },
    );
  }

  Future<void> revealLogout(WidgetTester tester) async {
    await tester.pumpAndSettle();
    expect(find.text('Identidad autenticada'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('CERRAR SESIÓN'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('CERRAR SESIÓN'), findsOneWidget);
  }

  Future<void> flushAsyncUi(WidgetTester tester) async {
    for (var i = 0; i < 8; i += 1) {
      await tester.pump(const Duration(milliseconds: 50));
    }
  }

  testWidgets('verified remote logout clears session and navigates to welcome',
      (tester) async {
    session.establish(accessToken: 'profile.jwt', account: account());
    var logoutCalls = 0;
    final logoutResponse = Completer<http.Response>();
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/auth/me') {
          return http.Response('{}', 503);
        }
        if (request.url.path == '/api/v1/auth/logout') {
          logoutCalls += 1;
          expect(request.headers['Authorization'], 'Bearer profile.jwt');
          return logoutResponse.future;
        }
        return http.Response('{}', 500);
      }),
    );

    await tester.pumpWidget(appFor(auth));
    await revealLogout(tester);
    await tester.tap(find.text('CERRAR SESIÓN'));
    await tester.pump();
    expect(logoutCalls, 1);
    expect(session.isAuthenticated, isTrue);

    logoutResponse.complete(http.Response('', 204));
    // Let the mocked platform storage future complete in the real async zone,
    // then settle the route transition. Fixed-duration pumps can advance frames
    // without draining a MethodChannel future and made this test timing-bound.
    await tester.runAsync(() async {
      await Future<void>.delayed(Duration.zero);
    });
    await tester.pumpAndSettle();

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(find.byType(ProfilePage), findsNothing);
    expect(find.text('WELCOME AFTER VERIFIED LOGOUT'), findsOneWidget);

    auth.dispose();
  });

  testWidgets('unverified remote logout preserves session and stays in Profile',
      (tester) async {
    session.establish(accessToken: 'profile.jwt', account: account());
    var logoutCalls = 0;
    final logoutResponse = Completer<http.Response>();
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/auth/logout') {
          logoutCalls += 1;
          return logoutResponse.future;
        }
        return http.Response('{}', 503);
      }),
    );

    await tester.pumpWidget(appFor(auth));
    await revealLogout(tester);
    await tester.tap(find.text('CERRAR SESIÓN'));
    await tester.pump();
    expect(logoutCalls, 1);

    logoutResponse.complete(http.Response('{}', 503));
    await flushAsyncUi(tester);

    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'profile.jwt');
    expect(find.byType(ProfilePage), findsOneWidget);
    expect(find.text('WELCOME AFTER VERIFIED LOGOUT'), findsNothing);

    auth.dispose();
  });
}
