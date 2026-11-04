import 'dart:convert';

import 'package:app/core/accessibility/accessible_status_message.dart';
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
        return http.Response(jsonEncode({'status': 'recovery_requested', 'message': 'generic'}), 202, headers: {'content-type': 'application/json'});
      }),
    );
    await service.requestPasswordRecovery(email: ' user@example.com ');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/v1/auth/recovery/request');
    expect(jsonDecode(captured.body), {'email': 'user@example.com'});
  });

  test('reset rejects invalid token and password before network call', () async {
    var called = false;
    final service = AthenaAuthService(baseUrl: 'http://athena.local', client: MockClient((request) async { called = true; return http.Response('', 204); }));
    final validLengthToken = List.filled(32, 't').join();
    expect(() => service.resetPassword(token: 'short-token', newPassword: 'a sufficiently long password'), throwsArgumentError);
    expect(() => service.resetPassword(token: validLengthToken, newPassword: 'too-short'), throwsArgumentError);
    expect(called, isFalse);
  });

  testWidgets('request success is generic and exposed as a live region', (tester) async {
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => http.Response('{"status":"recovery_requested","message":"generic"}', 202, headers: {'content-type': 'application/json'})),
    );
    await tester.pumpWidget(MaterialApp(home: PasswordRecoveryPage(service: service)));
    await tester.enterText(find.byKey(const Key('recovery-email')), 'unknown@example.com');
    await tester.tap(find.byKey(const Key('recovery-request')));
    await tester.pumpAndSettle();

    final statusFinder = find.byKey(const Key('recovery-generic-success'));
    expect(statusFinder, findsOneWidget);
    final status = tester.widget<AccessibleStatusMessage>(statusFinder);
    expect(status.message, contains('existe una cuenta válida'));
    expect(status.message, isNot(contains('unknown@example.com')));
    final semantics = tester.widget<Semantics>(find.descendant(of: statusFinder, matching: find.byType(Semantics)));
    expect(semantics.properties.liveRegion, isTrue);
    expect(semantics.properties.label, contains('Solicitud de recuperación procesada'));
  });

  testWidgets('recovery errors are announced without exposing token contents', (tester) async {
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async => http.Response('{"detail":"invalid"}', 400, headers: {'content-type': 'application/json'})),
    );
    final token = List.filled(43, 'z').join();
    await tester.pumpWidget(MaterialApp(home: PasswordRecoveryPage(initialToken: token, service: service)));
    await tester.enterText(find.byKey(const Key('recovery-password')), 'replacement password');
    await tester.enterText(find.byKey(const Key('recovery-password-confirm')), 'replacement password');
    await tester.ensureVisible(find.byKey(const Key('recovery-reset')));
    await tester.tap(find.byKey(const Key('recovery-reset')));
    await tester.pumpAndSettle();

    final errorFinder = find.byKey(const Key('recovery-error'));
    final error = tester.widget<AccessibleStatusMessage>(errorFinder);
    expect(error.semanticLabel, startsWith('Error de recuperación.'));
    expect(error.semanticLabel, isNot(contains(token)));
    final semantics = tester.widget<Semantics>(find.descendant(of: errorFinder, matching: find.byType(Semantics)));
    expect(semantics.properties.liveRegion, isTrue);
  });

  testWidgets('reset consumes link token, announces completion and requires fresh login', (tester) async {
    late Map<String, dynamic> resetPayload;
    final service = AthenaAuthService(
      baseUrl: 'http://athena.local',
      client: MockClient((request) async { resetPayload = jsonDecode(request.body) as Map<String, dynamic>; return http.Response('', 204); }),
    );
    final token = List.filled(43, 'z').join();
    await tester.pumpWidget(MaterialApp(home: PasswordRecoveryPage(initialToken: token, service: service)));
    await tester.enterText(find.byKey(const Key('recovery-password')), 'replacement password');
    await tester.enterText(find.byKey(const Key('recovery-password-confirm')), 'replacement password');
    await tester.ensureVisible(find.byKey(const Key('recovery-reset')));
    await tester.tap(find.byKey(const Key('recovery-reset')));
    await tester.pumpAndSettle();

    expect(resetPayload['token'], token);
    expect(resetPayload['newPassword'], 'replacement password');
    final completeFinder = find.byKey(const Key('recovery-reset-complete'));
    expect(completeFinder, findsOneWidget);
    final semantics = tester.widget<Semantics>(find.descendant(of: completeFinder, matching: find.byType(Semantics)));
    expect(semantics.properties.liveRegion, isTrue);
    expect(semantics.properties.label, contains('Debes iniciar sesión de nuevo'));
    expect(find.text('VOLVER A INICIAR SESIÓN'), findsOneWidget);
  });
}
