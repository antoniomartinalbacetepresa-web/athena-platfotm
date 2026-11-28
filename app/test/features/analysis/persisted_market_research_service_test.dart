import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/services/persisted_market_research_service.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _Store implements AuthTokenStore {
  @override
  Future<String?> readAccessToken() async => null;
  @override
  Future<void> writeAccessToken(String token) async {}
  @override
  Future<void> deleteAccessToken() async {}
}

void signIn(AuthSession session, int owner) {
  final now = DateTime.now().toUtc();
  session.establish(
    accessToken: 'owner-$owner',
    account: AuthAccount(
      id: owner,
      email: '$owner@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

PersistedMarketResearchDraft draft({List<String> sources = const []}) {
  final now = DateTime.now().toUtc().subtract(const Duration(seconds: 1));
  return PersistedMarketResearchDraft(
    instrumentId: 7,
    symbol: 'SYNTH',
    sourceProvider: 'synthetic_fixture',
    observedFrom: now.subtract(const Duration(days: 365)),
    observedTo: now,
    authoredAt: now,
    journalId: 'test-synthetic-review',
    sourceCycleHashes: sources,
    thesis: 'Human research question',
    contradiction: 'These are only fixtures',
  );
}

Map<String, dynamic> result(PersistedMarketResearchDraft request) => {
  'instrumentId': '7',
  'symbol': request.symbol,
  'asOf': request.asOf.toIso8601String(),
  'advisoryStatus': 'no_advice',
  'productionEligible': false,
  'isWeightingReady': false,
  'policy': {'automaticTrading': false, 'automaticProductionPromotion': false},
  'integrity': {'algorithm': 'sha256', 'cycleHash': 'a' * 64},
  'marketHistoryReference': {
    'referenceHash': 'b' * 64,
    'sourceRef': 'urn:athena:market-history:${'b' * 64}',
    'evidenceKind': 'synthetic_fixture',
    'metadataOnly': true,
    'licenceVerified': false,
    'historicalPointInTimeEligible': false,
    'productionEligible': false,
    'automaticTrading': false,
  },
};

http.Response privateDetail(
  PersistedMarketResearchDraft request, {
  String? defect,
}) {
  final journalId = '__athena_private_owner_1__:${request.journalId}';
  final sourceRef = 'urn:athena:market-history:${'b' * 64}';
  return http.Response(
    jsonEncode({
      'data': {
        'advisoryStatus': 'no_advice',
        'productionEligible': false,
        'automaticTrading': false,
        'isWeightingReady': false,
        'package': {
          'cycle': {
            'instrumentId': defect == 'instrument' ? '8' : '7',
            'symbol': request.symbol,
            'asOf': request.asOf.toIso8601String(),
            'journal': {'journalId': journalId, 'revisionId': 'r1'},
            'integrity': {'algorithm': 'sha256', 'cycleHash': 'a' * 64},
          },
          'journal': {
            'journalId': defect == 'owner'
                ? '__athena_private_owner_2__:other'
                : journalId,
            'revisionId': 'r1',
            'thesis': defect == 'thesis' ? 'other' : request.thesis,
            'references': [
              {'sourceRef': sourceRef},
              if (defect != 'source-cycle')
                for (final hash in request.sourceCycleHashes)
                  {'sourceRef': 'urn:athena:research-cycle:$hash'},
            ],
          },
          'radar': {
            'candidates': [
              {
                'evidence': [
                  {
                    'evidenceId': 'synthetic-history',
                    'category': 'data_quality',
                    'summary': 'Synthetic history',
                    'source': 'synthetic_fixture',
                    'availableAt': request.asOf.toIso8601String(),
                    'sourceRef': defect == 'reference'
                        ? 'urn:other'
                        : sourceRef,
                  },
                ],
              },
            ],
          },
        },
        'persistence': {'cycleHash': 'a' * 64},
      },
    }),
    200,
  );
}

void main() {
  test(
    'source cycle selections are immutable, strict and canonically ordered',
    () {
      final hashes = ['d' * 64, 'c' * 64, 'c' * 64];
      final request = draft(sources: hashes);
      hashes.clear();
      expect((jsonDecode(request.encodedBody) as Map)['sourceCycleHashes'], [
        'c' * 64,
        'd' * 64,
      ]);
      expect(() => request.sourceCycleHashes.clear(), throwsUnsupportedError);
      expect(() => draft(sources: ['bad']), throwsFormatException);
      expect(
        () => draft(sources: List.filled(6, 'c' * 64)),
        throwsFormatException,
      );
    },
  );
  for (final replaced in [false, true]) {
    test(
      'selected source cycles must match the private Journal: replaced=$replaced',
      () async {
        final session = AuthSession.forTesting(_Store());
        signIn(session, 1);
        final request = draft(sources: ['c' * 64]);
        final client = MockClient(
          (call) async => call.method == 'POST'
              ? http.Response(jsonEncode({'data': result(request)}), 200)
              : privateDetail(
                  request,
                  defect: replaced ? 'source-cycle' : null,
                ),
        );
        final service = PersistedMarketResearchService(
          client: client,
          session: session,
        );
        final future = service.create(request);
        if (replaced) {
          await expectLater(future, throwsFormatException);
        } else {
          expect((await future).symbol, 'SYNTH');
        }
        client.close();
      },
    );
  }

  for (final defect in ['instrument', 'owner', 'thesis', 'reference']) {
    test('creation rejects an unrelated private package: $defect', () async {
      final session = AuthSession.forTesting(_Store());
      signIn(session, 1);
      final request = draft();
      final client = MockClient(
        (call) async => call.method == 'POST'
            ? http.Response(jsonEncode({'data': result(request)}), 200)
            : privateDetail(request, defect: defect),
      );
      final service = PersistedMarketResearchService(
        client: client,
        session: session,
      );
      await expectLater(service.create(request), throwsFormatException);
      client.close();
    });
  }
  test('anonymous creation fails before any network request', () async {
    var calls = 0;
    final client = MockClient((_) async {
      calls++;
      return http.Response('{}', 200);
    });
    final service = PersistedMarketResearchService(
      client: client,
      session: AuthSession.forTesting(_Store()),
    );
    await expectLater(service.create(draft()), throwsStateError);
    expect(calls, 0);
    client.close();
  });

  test(
    'simultaneous submits share POST then owner-private verified retrieval',
    () async {
      final session = AuthSession.forTesting(_Store());
      signIn(session, 1);
      final request = draft();
      final methods = <String>[];
      final pending = Completer<http.Response>();
      final client = MockClient((call) async {
        methods.add(call.method);
        expect(call.headers['Authorization'], 'Bearer owner-1');
        if (call.method == 'POST') {
          expect(call.url.path, endsWith('/from-persisted-market-history'));
          expect(call.body, request.encodedBody);
          final body = jsonDecode(call.body) as Map<String, dynamic>;
          expect(body.containsKey('ownerId'), false);
          expect(body.containsKey('radarEvidence'), false);
          expect(body['asOf'], body['recordedAt']);
          return pending.future;
        }
        expect(call.url.path, endsWith('/research-cycle/private/${'a' * 64}'));
        return privateDetail(request);
      });
      final service = PersistedMarketResearchService(
        client: client,
        session: session,
      );
      final first = service.create(request);
      final second = service.create(request);
      expect(identical(first, second), true);
      pending.complete(
        http.Response(jsonEncode({'data': result(request)}), 200),
      );
      expect((await first).symbol, 'SYNTH');
      await second;
      expect(methods, ['POST', 'GET']);
      client.close();
    },
  );

  test(
    'uncertain write retry preserves exact cutoff and journal identity',
    () async {
      final session = AuthSession.forTesting(_Store());
      signIn(session, 1);
      final request = draft();
      final bodies = <String>[];
      final client = MockClient((call) async {
        if (call.method == 'GET') return privateDetail(request);
        bodies.add(call.body);
        if (bodies.length == 1) {
          throw http.ClientException('synthetic interruption');
        }
        return http.Response(jsonEncode({'data': result(request)}), 200);
      });
      final service = PersistedMarketResearchService(
        client: client,
        session: session,
      );
      await expectLater(
        service.create(request),
        throwsA(isA<http.ClientException>()),
      );
      await service.create(request);
      expect(bodies, [request.encodedBody, request.encodedBody]);
      client.close();
    },
  );

  test(
    'switching owner during POST rejects response before private retrieval',
    () async {
      final session = AuthSession.forTesting(_Store());
      signIn(session, 1);
      final request = draft();
      final pending = Completer<http.Response>();
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return pending.future;
      });
      final service = PersistedMarketResearchService(
        client: client,
        session: session,
      );
      final future = service.create(request);
      signIn(session, 2);
      pending.complete(
        http.Response(jsonEncode({'data': result(request)}), 200),
      );
      await expectLater(future, throwsStateError);
      expect(calls, 1);
      client.close();
    },
  );

  for (final defect in [
    'symbol',
    'instrument',
    'cutoff',
    'hash',
    'license',
    'trading',
  ]) {
    test('rejects incompatible creation result: $defect', () async {
      final session = AuthSession.forTesting(_Store());
      signIn(session, 1);
      final request = draft();
      final data = result(request);
      var calls = 0;
      if (defect == 'symbol') data['symbol'] = 'OTHER';
      if (defect == 'instrument') data['instrumentId'] = '8';
      if (defect == 'cutoff') {
        data['asOf'] = request.asOf
            .subtract(const Duration(days: 1))
            .toIso8601String();
      }
      if (defect == 'hash') (data['integrity'] as Map)['cycleHash'] = 'invalid';
      if (defect == 'license') {
        (data['marketHistoryReference'] as Map)['licenceVerified'] = true;
      }
      if (defect == 'trading') {
        (data['policy'] as Map)['automaticTrading'] = true;
      }
      final client = MockClient((_) async {
        calls++;
        return http.Response(jsonEncode({'data': data}), 200);
      });
      final service = PersistedMarketResearchService(
        client: client,
        session: session,
      );
      await expectLater(service.create(request), throwsFormatException);
      expect(calls, 1);
      client.close();
    });
  }

  for (final status in [400, 401, 403, 404, 409, 422, 503]) {
    test(
      'HTTP $status never falls back to public creation or retrieval',
      () async {
        final session = AuthSession.forTesting(_Store());
        signIn(session, 1);
        var calls = 0;
        final client = MockClient((_) async {
          calls++;
          return http.Response('{}', status);
        });
        final service = PersistedMarketResearchService(
          client: client,
          session: session,
        );
        await expectLater(
          service.create(draft()),
          const {400, 404, 409, 422}.contains(status)
              ? throwsA(isA<PersistedMarketResearchRejected>())
              : throwsStateError,
        );
        expect(calls, 1);
        client.close();
      },
    );
  }
}
