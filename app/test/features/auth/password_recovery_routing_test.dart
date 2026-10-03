import 'package:app/core/routing/app_router.dart';
import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/auth/presentation/pages/login_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('login exposes recovery route', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        onGenerateRoute: AppRouter.generate,
        home: const LoginPage(),
      ),
    );

    await tester.tap(find.byKey(const Key('login-recovery')));
    await tester.pumpAndSettle();

    expect(find.text('RECUPERAR ACCESO'), findsOneWidget);
    expect(find.byKey(const Key('recovery-email')), findsOneWidget);
  });

  testWidgets('recovery route consumes token from HTTPS-style query', (tester) async {
    final token = List.filled(43, 'q').join();
    await tester.pumpWidget(
      MaterialApp(
        onGenerateRoute: AppRouter.generate,
        initialRoute: '${AppRoutes.recovery}?token=$token',
      ),
    );
    await tester.pumpAndSettle();

    final field = tester.widget<TextField>(
      find.byKey(const Key('recovery-token')),
    );
    expect(field.controller!.text, token);
  });
}
