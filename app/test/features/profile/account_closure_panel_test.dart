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

    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      'current-passphrase',
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    await tester.tap(find.byKey(const Key('account-closure-submit')));
    await tester.pump();

    expect(password, 'current-passphrase');
    expect(completed, 1);
    expect(find.byKey(const Key('account-closure-error')), findsNothing);
  });

  testWidgets('backend rejection keeps the form open and shows a safe error',
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

    await tester.enterText(
      find.byKey(const Key('account-closure-password')),
      'wrong-passphrase',
    );
    await tester.enterText(
      find.byKey(const Key('account-closure-confirmation')),
      'ELIMINAR',
    );
    await tester.tap(find.byKey(const Key('account-closure-submit')));
    await tester.pumpAndSettle();

    expect(calls, 1);
    expect(completed, 0);
    expect(find.byKey(const Key('account-closure-error')), findsOneWidget);
    expect(find.textContaining('sensitive backend detail'), findsNothing);
    expect(
      tester.widget<ElevatedButton>(
        find.byKey(const Key('account-closure-submit')),
      ).onPressed,
      isNotNull,
    );
  });
}
