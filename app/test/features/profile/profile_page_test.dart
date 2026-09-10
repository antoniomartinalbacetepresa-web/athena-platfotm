import 'package:app/core/routing/app_router.dart';
import 'package:app/core/routing/app_routes.dart';
import 'package:app/features/profile/models/user_preferences.dart';
import 'package:app/features/profile/presentation/pages/profile_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('profile route renders protected guest state without a session',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        onGenerateRoute: AppRouter.generate,
        initialRoute: AppRoutes.profile,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(ProfilePage), findsOneWidget);
    expect(find.text('PERFIL'), findsOneWidget);
    expect(find.text('Perfil protegido'), findsOneWidget);
    expect(find.text('INICIAR SESIÓN'), findsOneWidget);
    expect(find.text('Preferencias protegidas'), findsNothing);
  });

  testWidgets('preferences form validates and emits only the protected model',
      (tester) async {
    UserPreferences? saved;
    var reloadCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ProfilePreferencesForm(
              preferences: const UserPreferences(
                riskTolerance: 'balanced',
                investmentHorizonYears: 10,
                baseCurrency: 'EUR',
                objective: 'balanced_growth',
              ),
              busy: false,
              onReload: () async => reloadCount += 1,
              onSave: (value) async => saved = value,
            ),
          ),
        ),
      ),
    );

    expect(find.text('Preferencias protegidas'), findsOneWidget);
    expect(find.text('Preferencias cargadas desde almacenamiento cifrado.'),
        findsOneWidget);

    final textFields = find.byType(TextFormField);
    expect(textFields, findsNWidgets(2));

    await tester.enterText(textFields.at(0), '0');
    await tester.tap(find.text('GUARDAR'));
    await tester.pump();
    expect(find.text('Introduce un horizonte entre 1 y 60 años.'), findsOneWidget);
    expect(saved, isNull);

    await tester.enterText(textFields.at(0), '15');
    await tester.enterText(textFields.at(1), 'usd');
    await tester.tap(find.text('GUARDAR'));
    await tester.pump();

    expect(saved, isNotNull);
    expect(saved!.riskTolerance, 'balanced');
    expect(saved!.investmentHorizonYears, 15);
    expect(saved!.baseCurrency, 'USD');
    expect(saved!.objective, 'balanced_growth');

    await tester.tap(find.text('RECARGAR'));
    await tester.pump();
    expect(reloadCount, 1);
  });
}
