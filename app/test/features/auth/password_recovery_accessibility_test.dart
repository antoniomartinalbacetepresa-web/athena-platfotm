import 'package:app/features/auth/data/auth_api_client.dart';
import 'package:app/features/auth/presentation/pages/password_recovery_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _RecoveryAuthClient extends AuthApiClient {
  _RecoveryAuthClient({this.onRequest});

  final Future<void> Function(String email)? onRequest;

  @override
  Future<void> requestPasswordRecovery({required String email}) async {
    await onRequest?.call(email);
  }
}

Widget _app(AuthApiClient client) => MaterialApp(
      home: PasswordRecoveryPage(authApiClient: client),
    );

void main() {
  testWidgets('password recovery remains keyboard-submittable and exposes labelled controls',
      (tester) async {
    String? submittedEmail;
    await tester.pumpWidget(_app(_RecoveryAuthClient(
      onRequest: (email) async => submittedEmail = email,
    )));

    expect(find.text('Recuperar contraseña'), findsWidgets);
    expect(find.text('Correo electrónico'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Enviar enlace'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Volver al inicio de sesión'), findsOneWidget);

    final emailField = tester.widget<TextFormField>(find.byType(TextFormField));
    expect(emailField.keyboardType, TextInputType.emailAddress);
    expect(emailField.autocorrect, isFalse);
    expect(emailField.enableSuggestions, isFalse);

    await tester.enterText(find.byType(TextFormField), 'investor@example.com');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(submittedEmail, 'investor@example.com');
    expect(find.text('Si la cuenta existe, recibirás un enlace de recuperación.'), findsOneWidget);
  });

  testWidgets('password recovery validation is visible without issuing a request',
      (tester) async {
    var requests = 0;
    await tester.pumpWidget(_app(_RecoveryAuthClient(
      onRequest: (_) async => requests++,
    )));

    await tester.tap(find.widgetWithText(FilledButton, 'Enviar enlace'));
    await tester.pump();

    expect(find.text('Introduce un correo válido.'), findsOneWidget);
    expect(requests, 0);
  });
}
