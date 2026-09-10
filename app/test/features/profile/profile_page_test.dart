import 'package:app/core/routing/app_router.dart';
import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/profile/presentation/pages/profile_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('profile route renders the initial profile surface', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        onGenerateRoute: AppRouter.generate,
        initialRoute: AppRoutes.profile,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(ProfilePage), findsOneWidget);
    expect(find.text('PERFIL'), findsOneWidget);
    expect(find.text('Datos personales'), findsOneWidget);
    expect(find.text('Preferencias'), findsOneWidget);
    expect(find.text('Perfil de riesgo'), findsOneWidget);
    expect(find.text('Idioma'), findsOneWidget);
  });
}
