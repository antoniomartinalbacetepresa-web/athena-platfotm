import 'dart:convert';

import 'package:app/features/auth/presentation/pages/password_recovery_page.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('recovery request sends normalized email and accepts generic contract', () async {
    late http.Request captured;
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'status': 'recovery_requested',
            'message': 'Si existe una cuenta válida para ese email, se enviarán instrucciones de recuperación.',
          }),
          202,
          headers: {'content-type': 'application/json'},
        );
      }),
    );

    await service.requestPasswordRecovery(email: ' user@example.com ');

    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/recovery/request');
    expect(captured.headers['Content-Type'], 'application/json');
    final payload = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(payload, {'email': 'user@example.com'});
  });

  test('reset rejects invalid token and password before network call', () async {
    var called = false;
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        called = true;
        return http.Response('', 204);
      }),
    );
    final validLengthToken = List.filled(32, 't').join();

    expect(
      () => service.resetPassword(
        token: 'short-token',
        newPassword: 'a sufficiently long password',
      ),
      throwsArgumentError,
    );
    expect(
      () => service.resetPassword(
        token: validLengthToken,
        newPassword: 'too-short',
      ),
      throwsArgumentError,
    );
    expect(called, isFalse);
  });

  test('reset sends recovery token and new password without creating a session', () async {
    late http.Request captured;
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        captured = request;
        return http.Response('', 204);
      }),
    );
    final recoveryToken = List.filled(43, 'r').join();

    await service.resetPassword(
      token: recoveryToken,
      newPassword: 'new password value',
    );

    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/recovery/reset');
    final payload = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(payload['token'], recoveryToken);
    expect(payload['newPassword'], 'new password value');
    expect(captured.headers['Authorization'], isNull);
  });

  testWidgets('request UI only shows generic anti-enumeration success', (tester) async {
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => http.Response(
            '{"status":"recovery_requested","message":"generic"}',
            202,
            headers: {'content-type': 'application/json'},
          )),
    );

    await tester.pumpWidget(
      MaterialApp(home: PasswordRecoveryPage(service: service)),
    );
    await tester.enterText(
      find.byKey(const Key('recovery-email')),
      'unknown@example.com',
    );
    await tester.tap(find.byKey(const Key('recovery-request')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('recovery-generic-success')), findsOneWidget);
    expect(find.textContaining('existe una cuenta válida'), findsOneWidget);
    expect(find.textContaining('unknown@example.com'), findsNothing);
  });

  testWidgets('reset UI consumes initial link token and requires fresh login', (tester) async {
    late Map<String, dynamic> resetPayload;
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async {
        resetPayload = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response('', 204);
      }),
    );
    final token = List.filled(43, 'z').join();

    await tester.pumpWidget(
      MaterialApp(
        home: PasswordRecoveryPage(
          initialToken: token,
          service: service,
        ),
      ),
    );

    expect(
      tester.widget<TextField>(find.byKey(const Key('recovery-token'))).controller!.text,
      token,
    );
    await tester.enterText(
      find.byKey(const Key('recovery-password')),
      'replacement password',
    );
    await tester.enterText(
      find.byKey(const Key('recovery-password-confirm')),
      'replacement password',
    );
    await tester.ensureVisible(find.byKey(const Key('recovery-reset')));
    await tester.tap(find.byKey(const Key('recovery-reset')));
    await tester.pumpAndSettle();

    expect(resetPayload['token'], token);
    expect(resetPayload['newPassword'], 'replacement password');
    expect(find.text('Contraseña restablecida'), findsOneWidget);
    expect(find.text('VOLVER A INICIAR SESIÓN'), findsOneWidget);
  });
}
