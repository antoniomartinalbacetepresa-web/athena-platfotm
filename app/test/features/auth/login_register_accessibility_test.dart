import 'package:app/features/auth/presentation/pages/login_page.dart';
import 'package:app/features/auth/presentation/pages/register_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('login exposes a stable keyboard and autofill accessibility contract',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(const MaterialApp(home: LoginPage()));

    expect(find.byKey(const Key('login-heading')), findsOneWidget);
    expect(find.byKey(const Key('login-email')), findsOneWidget);
    expect(find.byKey(const Key('login-password')), findsOneWidget);
    expect(find.byKey(const Key('login-submit')), findsOneWidget);
    expect(find.byKey(const Key('login-recovery')), findsOneWidget);
    expect(find.byKey(const Key('login-register')), findsOneWidget);
    expect(find.byKey(const Key('login-guest')), findsOneWidget);

    final email = tester.widget<TextField>(find.byKey(const Key('login-email')));
    final password =
        tester.widget<TextField>(find.byKey(const Key('login-password')));
    expect(email.keyboardType, TextInputType.emailAddress);
    expect(email.textInputAction, TextInputAction.next);
    expect(email.autofillHints, contains(AutofillHints.email));
    expect(password.textInputAction, TextInputAction.done);
    expect(password.autofillHints, contains(AutofillHints.password));
    expect(password.obscureText, isTrue);

    final headingSemantics = tester.widget<Semantics>(
      find.ancestor(
        of: find.byKey(const Key('login-heading')),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(headingSemantics.properties.header, isTrue);

    semantics.dispose();
  });

  testWidgets('registration exposes ordered keyboard and new-credential autofill',
      (tester) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(const MaterialApp(home: RegisterPage()));

    expect(find.byKey(const Key('register-heading')), findsOneWidget);
    expect(find.byKey(const Key('register-name')), findsOneWidget);
    expect(find.byKey(const Key('register-email')), findsOneWidget);
    expect(find.byKey(const Key('register-password')), findsOneWidget);
    expect(find.byKey(const Key('register-confirm-password')), findsOneWidget);
    expect(find.byKey(const Key('register-submit')), findsOneWidget);
    expect(find.byKey(const Key('register-login')), findsOneWidget);

    final name = tester.widget<TextField>(find.byKey(const Key('register-name')));
    final email = tester.widget<TextField>(find.byKey(const Key('register-email')));
    final password =
        tester.widget<TextField>(find.byKey(const Key('register-password')));
    final confirmation = tester.widget<TextField>(
      find.byKey(const Key('register-confirm-password')),
    );

    expect(name.textInputAction, TextInputAction.next);
    expect(name.autofillHints, contains(AutofillHints.name));
    expect(email.keyboardType, TextInputType.emailAddress);
    expect(email.textInputAction, TextInputAction.next);
    expect(email.autofillHints, contains(AutofillHints.newUsername));
    expect(password.textInputAction, TextInputAction.next);
    expect(password.autofillHints, contains(AutofillHints.newPassword));
    expect(password.obscureText, isTrue);
    expect(confirmation.textInputAction, TextInputAction.done);
    expect(confirmation.autofillHints, contains(AutofillHints.newPassword));
    expect(confirmation.obscureText, isTrue);

    final headingSemantics = tester.widget<Semantics>(
      find.ancestor(
        of: find.byKey(const Key('register-heading')),
        matching: find.byType(Semantics),
      ).first,
    );
    expect(headingSemantics.properties.header, isTrue);

    semantics.dispose();
  });
}
