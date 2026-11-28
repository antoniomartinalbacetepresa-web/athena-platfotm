import 'package:app/features/auth/services/athena_auth_account_closure.dart';
import 'package:app/features/auth/services/athena_auth_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('whitespace-only closure password is rejected before network transport', () async {
    var networkCalls = 0;
    final client = MockClient((request) async {
      networkCalls += 1;
      return http.Response('', 204);
    });
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: client,
    );

    await expectLater(
      auth.closeAccount(
        token: 'test-access-token',
        currentPassword: '   \t\n',
      ),
      throwsArgumentError,
    );

    expect(networkCalls, 0);
  });

  test('closure password is never trimmed before reauthentication transport', () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response('', 204);
    });
    final auth = AthenaAuthService(
      baseUrl: 'https://athena.local',
      client: client,
    );

    await auth.closeAccount(
      token: '  test-access-token  ',
      currentPassword: ' valid password with spaces ',
    );

    expect(captured.headers['Authorization'], 'Bearer test-access-token');
    expect(captured.body, contains(' valid password with spaces '));
  });
}
