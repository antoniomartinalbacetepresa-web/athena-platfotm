import 'package:app/features/auth/services/athena_auth_account_closure.dart';
import 'package:app/features/profile/presentation/widgets/account_closure_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Widget harness({
    required Future<void> Function(String password) onClose,
    VoidCallback? onClosed,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: AccountClosurePanel(
            onClose: onClose,
            onCancel: () {},
            onClosed: onClosed ?? () {},
          ),
        ),
      ),
    );
  }

  Future<void> submit(WidgetTester tester, String password) async {
    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      password,
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    await tester.tap(find.byKey(const Key('account-closure-submit')));
    await tester.pumpAndSettle();
  }

  testWidgets('closure requires password and exact destructive confirmation',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(harness(onClose: (_) async => calls += 1));

    final submit = find.byKey(const Key('account-closure-submit'));
    expect(find.byKey(const Key('account-closure-retention-note')), findsOneWidget);
    expect(
      tester.widget<TextField>(find.byKey(const Key('account-closure-password')))
          .obscureText,
      isTrue,
    );
    expect(tester.widget<ElevatedButton>(submit).onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      'current-passphrase',
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'eliminar',
    );
    expect(tester.widget<ElevatedButton>(submit).onPressed, isNull);
    expect(calls, 0);

    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    expect(tester.widget<ElevatedButton>(submit).onPressed, isNotNull);
  });

  testWidgets('successful closure forwards reauthentication and completes once',
      (tester) async {
    String? password;
    var completed = 0;
    await tester.pumpWidget(
      harness(
        onClose: (value) async => password = value,
        onClosed: () => completed += 1,
      ),
    );

    await submit(tester, 'current-passphrase');

    expect(password, 'current-passphrase');
    expect(completed, 1);
    expect(find.byKey(const Key('account-closure-error')), findsNothing);
  });

  testWidgets('reauthentication rejection explains that account and session remain',
      (tester) async {
    var completed = 0;
    await tester.pumpWidget(
      harness(
        onClose: (_) async => throw const AccountClosureRejectedException(401),
        onClosed: () => completed += 1,
      ),
    );

    await submit(tester, 'wrong-passphrase');

    expect(completed, 0);
    expect(find.byKey(const Key('account-closure-error')), findsOneWidget);
    expect(
      find.text(
        'La contraseña actual no es correcta. La cuenta sigue abierta y la sesión se conserva.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('service failure stays generic and does not expose backend detail',
      (tester) async {
    var completed = 0;
    var calls = 0;
    await tester.pumpWidget(
      harness(
        onClose: (_) async {
          calls += 1;
          throw StateError('sensitive backend detail');
        },
        onClosed: () => completed += 1,
      ),
    );

    await submit(tester, 'current-passphrase');

    expect(calls, 1);
    expect(completed, 0);
    expect(find.byKey(const Key('account-closure-error')), findsOneWidget);
    expect(find.textContaining('sensitive backend detail'), findsNothing);
    expect(
      find.text(
        'No se pudo confirmar el cierre de la cuenta. Vuelve a intentarlo cuando el servicio esté disponible.',
      ),
      findsOneWidget,
    );
    expect(
      tester.widget<ElevatedButton>(
        find.byKey(const Key('account-closure-submit')),
      ).onPressed,
      isNotNull,
    );
  });
}
