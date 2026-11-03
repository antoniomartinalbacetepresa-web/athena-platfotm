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
        '"package":{"symbol":"AAPL","asOf":"${now.toIso8601String()}"},"persistence":{"cycleHash":"$hash"}}}',
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

  test('private detail rejects a mismatched PIT timestamp', () async {
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
    final hash = 'c' * 64;
    final wrongAsOf = now.subtract(const Duration(days: 1)).toIso8601String();
    final client = MockClient((request) async => http.Response(
      '{"data":{"advisoryStatus":"no_advice","productionEligible":false,'
      '"automaticTrading":false,"isWeightingReady":false,'
      '"package":{"symbol":"AAPL","asOf":"$wrongAsOf"},'
      '"persistence":{"cycleHash":"$hash"}}}',
      200,
    ));
    final service = PrivateResearchHistoryService(client: client, session: session);
    await expectLater(
      service.loadCycle(PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now)),
      throwsFormatException,
    );
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
      '"package":{"symbol":"AAPL","asOf":"${now.toIso8601String()}"},"persistence":{"cycleHash":"$hash"}}}',
      200,
    ));
    await expectLater(pending, throwsStateError);
    service.dispose();
    client.close();
  });

  test('private detail denial never falls back to public research', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'denied-owner-token',
      account: AuthAccount(
        id: 1,
        email: 'owner@example.invalid',
        isActive: true,
        createdAt: now,
        updatedAt: now,
      ),
    );
    final hash = 'd' * 64;
    final paths = <String>[];
    final client = MockClient((request) async {
      paths.add(request.url.path);
      return http.Response('{"detail":"Forbidden"}', 403);
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    await expectLater(
      service.loadCycle(PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now)),
      throwsStateError,
    );
    expect(paths, <String>[
      '/api/v1/recommendations/professional-research/research-cycle/private/$hash',
    ]);
    service.dispose();
    client.close();
  });

  test('private News synthesis is owner-scoped and rejects unverifiable model status', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'owner-token',
      account: AuthAccount(id: 1, email: 'owner@example.invalid',
          isActive: true, createdAt: now, updatedAt: now),
    );
    final hash = 'e' * 64;
    final paths = <String>[];
    final client = MockClient((request) async {
      paths.add(request.url.path);
      expect(request.headers['Authorization'], 'Bearer owner-token');
      return http.Response(
        '{"data":{"cycleBindingVerified":true,"automaticTrading":false,'
        '"recommendationInfluence":false,"synthesis":{'
        '"modelExecutionVerified":false,"summary":"Research only"},'
        '"persistence":{"cycleHash":"$hash"}}}', 200);
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final entry = PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now);
    final result = await service.loadSynthesis(entry, athena: false);
    expect(result!.summary, 'Research only');
    expect(paths, ['/api/v1/recommendations/professional-research/research-cycle/private/$hash/news-synthesis']);
    service.dispose();
    client.close();
  });


  test('private ATHENA synthesis validates canonical binding and provenance', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'owner-token',
      account: AuthAccount(id: 1, email: 'owner@example.invalid',
          isActive: true, createdAt: now, updatedAt: now),
    );
    final hash = 'f' * 64;
    final client = MockClient((request) async {
      expect(request.url.path, endsWith('/research-cycle/private/$hash/athena-synthesis'));
      expect(request.headers['Authorization'], 'Bearer owner-token');
      return http.Response(
        '{"data":{"artifactBindingVerified":true,"provenance":{},'
        '"synthesis":{"modelExecutionVerified":false,"summary":"Human review only"},'
        '"persistence":{"cycleHash":"$hash"}}}', 200);
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final entry = PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now);
    final result = await service.loadSynthesis(entry, athena: true);
    expect(result!.kind, 'ATHENA');
    expect(result.summary, 'Human review only');
    service.dispose();
    client.close();
  });

  test('private synthesis rejects a response after account switch', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'first-token',
      account: AuthAccount(id: 1, email: 'first@example.invalid',
          isActive: true, createdAt: now, updatedAt: now),
    );
    final pendingResponse = Completer<http.Response>();
    final client = MockClient((request) async {
      expect(request.headers['Authorization'], 'Bearer first-token');
      return pendingResponse.future;
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final hash = 'a' * 64;
    final pending = service.loadSynthesis(
      PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now),
      athena: false,
    );
    session.establish(
      accessToken: 'second-token',
      account: AuthAccount(id: 2, email: 'second@example.invalid',
          isActive: true, createdAt: now, updatedAt: now),
    );
    pendingResponse.complete(http.Response(
      '{"data":{"cycleBindingVerified":true,"automaticTrading":false,'
      '"recommendationInfluence":false,"synthesis":{'
      '"modelExecutionVerified":false,"summary":"Must not leak"},'
      '"persistence":{"cycleHash":"$hash"}}}', 200));
    await expectLater(pending, throwsStateError);
    service.dispose();
    client.close();
  });


  test('private synthesis 404 is unavailable and never uses public fallback', () async {
    final session = AuthSession.forTesting(_TokenStore());
    final now = DateTime.now().toUtc();
    session.establish(
      accessToken: 'owner-token',
      account: AuthAccount(id: 1, email: 'owner@example.invalid',
          isActive: true, createdAt: now, updatedAt: now),
    );
    final hash = 'b' * 64;
    final paths = <String>[];
    final client = MockClient((request) async {
      paths.add(request.url.path);
      expect(request.headers['Authorization'], 'Bearer owner-token');
      return http.Response('{"detail":"Not found"}', 404);
    });
    final service = PrivateResearchHistoryService(client: client, session: session);
    final result = await service.loadSynthesis(
      PrivateResearchEntry(cycleHash: hash, symbol: 'AAPL', asOf: now),
      athena: true,
    );
    expect(result, isNull);
    expect(paths, [
      '/api/v1/recommendations/professional-research/research-cycle/private/$hash/athena-synthesis',
    ]);
    service.dispose();
    client.close();
  });


}
