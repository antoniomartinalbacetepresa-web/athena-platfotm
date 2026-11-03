import 'dart:async';

import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/models/auth_account.dart';
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
  test('oversized authenticated history is rejected before JSON parsing', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'test-token',
      account: AuthAccount(
        id: 1,
        email: 'test@example.invalid',
        isActive: true,
        createdAt: now,
        updatedAt: now,
      ),
    );
    var requests = 0;
    final client = MockClient((request) async {
      requests++;
      expect(request.headers['Authorization'], 'Bearer test-token');
      return http.Response('x' * (PrivateResearchHistoryService.maxResponseBytes + 1), 200);
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    await expectLater(service.load(symbol: 'AAPL'), throwsFormatException);
    expect(requests, 1);
    service.dispose();
    client.close();
  });

  test('owner-scoped detail uses private route and validates cycle binding', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'test-token',
      account: AuthAccount(
        id: 1,
        email: 'test@example.invalid',
        isActive: true,
        createdAt: now,
        updatedAt: now,
      ),
    );
    final hash = 'a' * 64;
    var requests = 0;
    final client = MockClient((request) async {
      requests++;
      expect(request.url.path, endsWith('/research-cycle/private/$hash'));
      expect(request.headers['Authorization'], 'Bearer test-token');
      return http.Response(
        '{"data":{"advisoryStatus":"no_advice","productionEligible":false,'
        '"automaticTrading":false,"isWeightingReady":false,'
        '"package":{"symbol":"AAPL"},"persistence":{"cycleHash":"$hash"}}}',
        200,
      );
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final detail = await service.loadCycle(
      PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now),
    );
    expect(detail.cycleHash, hash);
    expect(detail.symbol, 'AAPL');
    expect(requests, 1);
    service.dispose();
    client.close();
  });

  test('account switch during private detail request rejects stale response', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'owner-one-token',
      account: AuthAccount(
        id: 1,
        email: 'one@example.invalid',
        isActive: true,
        createdAt: now,
        updatedAt: now,
      ),
    );
    final hash = 'b' * 64;
    final pendingResponse = Completer<http.Response>();
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer owner-one-token');
      return pendingResponse.future;
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final pending = service.loadCycle(
      PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now),
    );
    session.establish(
      accessToken: 'owner-two-token',
      account: AuthAccount(
        id: 2,
        email: 'two@example.invalid',
        isActive: true,
        createdAt: now,
        updatedAt: now,
      ),
    );
    pendingResponse.complete(http.Response(
      '{"data":{"advisoryStatus":"no_advice","productionEligible":false,'
      '"automaticTrading":false,"isWeightingReady":false,'
      '"package":{"symbol":"AAPL"},"persistence":{"cycleHash":"$hash"}}}',
      200,
    ));
    await expectLater(pending, throwsStateError);
    service.dispose();
    client.close();
  });

}
