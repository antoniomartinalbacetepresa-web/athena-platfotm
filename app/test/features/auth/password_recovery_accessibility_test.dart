import 'dart:convert';

import 'package:app/features/auth/presentation/pages/password_recovery_page.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

AthenaAuthService _service({Future<void> Function(String email)? onRequest}) {
  return AthenaAuthService(
    baseUrl: 'http://athena.local',
    client: MockClient((request) async {
      final payload = jsonDecode(request.body) as Map<String, dynamic>;
      await onRequest?.call(payload['email'] as String);
      return http.Response(
        '{"status":"recovery_requested","message":"generic"}',
        202,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
}

void main() {
  testWidgets('password recovery remains keyboard-submittable and exposes labelled controls',
      (tester) async {
    String? submittedEmail;
    await tester.pumpWidget(MaterialApp(
      home: PasswordRecoveryPage(
        service: _service(onRequest: (email) async => submittedEmail = email),
      ),
    ));

    expect(find.text('Recuperar contraseña'), findsWidgets);
    expect(find.text('Correo electrónico'), findsOneWidget);
    expect(find.byKey(const Key('recovery-request')), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('recovery-email')),
      'investor@example.com',
    );
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(submittedEmail, 'investor@example.com');
    expect(find.byKey(const Key('recovery-generic-success')), findsOneWidget);
  });

  testWidgets('password recovery validation is visible without issuing a request',
      (tester) async {
    var requests = 0;
    await tester.pumpWidget(MaterialApp(
      home: PasswordRecoveryPage(
        service: _service(onRequest: (_) async => requests++),
      ),
    ));

    await tester.tap(find.byKey(const Key('recovery-request')));
    await tester.pump();

    expect(find.text('Introduce un correo válido.'), findsOneWidget);
    expect(requests, 0);
  });
}
