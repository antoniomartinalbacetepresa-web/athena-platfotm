import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/welcome/presentation/pages/welcome_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _EmptyAuthTokenStore implements AuthTokenStore {
  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<void> writeAccessToken(String token) async {}

  @override
  Future<void> deleteAccessToken() async {}
}

void main() {
  testWidgets(
    'welcome exposes account and guest routes without granting protected authority',
    (tester) async {
      final visited = <String>[];
      final authSession = AuthSession.forTesting(_EmptyAuthTokenStore());

      await tester.pumpWidget(
        MaterialApp(
          home: WelcomePage(authSession: authSession),
          onGenerateRoute: (settings) {
            visited.add(settings.name!);
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => Text('route:${settings.name}'),
            );
          },
        ),
      );

      // The injected store represents a clean install with no durable credential.
      // One pump completes that deterministic restore without platform storage.
      await tester.pump();

      expect(find.text('ENTRAR CON CUENTA'), findsOneWidget);
      expect(find.text('Continuar como invitado'), findsOneWidget);
      expect(
        find.textContaining(
          'Las funciones de perfil protegido requieren una cuenta autenticada.',
        ),
        findsOneWidget,
      );

      await tester.tap(find.text('ENTRAR CON CUENTA'));
      // Session restoration is complete at this point; settle only the finite
      // Material route transition so the destination is actually rendered.
      await tester.pumpAndSettle();
      expect(visited.last, AppRoutes.login);
      expect(find.text('route:${AppRoutes.login}'), findsOneWidget);
    },
  );
}
