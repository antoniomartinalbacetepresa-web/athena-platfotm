import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _TokenStore implements AuthTokenStore {
  @override
  Future<String?> readAccessToken() async => null;
  @override
  Future<void> writeAccessToken(String token) async {}
  @override
  Future<void> deleteAccessToken() async {}
}

void main() {
  test('anonymous private research history fails before contacting backend', () async {
    var requests = 0;
    final client = MockClient((request) async {
      requests++;
      return http.Response('{}', 200);
    });
    final service = PrivateResearchHistoryService(
      client: client, session: AuthSession.forTesting(_TokenStore()),
    );
    await expectLater(service.load(symbol: 'AAPL'), throwsStateError);
    expect(requests, 0);
    service.dispose();
    client.close();
  });

  test('invalid symbols fail before contacting backend', () async {
    var requests = 0;
    final client = MockClient((request) async {
      requests++;
      return http.Response('{}', 200);
    });
    final service = PrivateResearchHistoryService(
      client: client, session: AuthSession.forTesting(_TokenStore()),
    );
    await expectLater(service.load(symbol: '../other'), throwsFormatException);
    expect(requests, 0);
    service.dispose();
    client.close();
  });
}
