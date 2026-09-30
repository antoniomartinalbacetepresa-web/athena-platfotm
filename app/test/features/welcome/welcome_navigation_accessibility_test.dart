import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/welcome/presentation/pages/welcome_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'welcome exposes account and guest routes without granting protected authority',
    (tester) async {
      final visited = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: const WelcomePage(),
          onGenerateRoute: (settings) {
            visited.add(settings.name!);
            return MaterialPageRoute<void>(
              settings: settings,
              builder: (_) => Text('route:${settings.name}'),
            );
          },
        ),
      );

      // Welcome restores a durable session before exposing either public route.
      // Advance bounded frames instead of pumpAndSettle: this lets the async
      // secure-storage validation complete without waiting on unrelated animations.
      for (var i = 0; i < 20 && find.text('ENTRAR CON CUENTA').evaluate().isEmpty; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      expect(find.text('ENTRAR CON CUENTA'), findsOneWidget);
      expect(find.text('Continuar como invitado'), findsOneWidget);
      expect(
        find.textContaining(
          'Las funciones de perfil protegido requieren una cuenta autenticada.',
        ),
        findsOneWidget,
      );

      await tester.tap(find.text('ENTRAR CON CUENTA'));
      await tester.pump();
      expect(visited.last, AppRoutes.login);
      expect(find.text('route:${AppRoutes.login}'), findsOneWidget);
    },
  );
}
