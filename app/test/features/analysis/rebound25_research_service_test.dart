import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/services/rebound25_research_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../../fixtures/rebound25_response_fixture.dart';

class _Store implements AuthTokenStore {
  @override
  Future<String?> readAccessToken() async => null;
  @override
  Future<void> writeAccessToken(String token) async {}
  @override
  Future<void> deleteAccessToken() async {}
}

AuthSession session({bool authenticated = true}) {
  final value = AuthSession.forTesting(_Store());
  if (authenticated) login(value, 1);
  return value;
}

void login(AuthSession value, int owner) {
  final now = DateTime.now().toUtc();
  value.establish(
    accessToken: 'synthetic-owner-$owner',
    account: AuthAccount(
      id: owner,
      email: '$owner@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

Map<String, dynamic> requestFixture() =>
    jsonDecode(rebound25RequestFixture) as Map<String, dynamic>;
Map<String, dynamic> dataFixture() =>
    (jsonDecode(rebound25ResponseFixture) as Map<String, dynamic>)['data']
        as Map<String, dynamic>;

void main() {
  test('parses exact backend fixture and keeps reports immutable', () {
    final result = Rebound25ResearchResult.fromJson(
      dataFixture(),
      request: requestFixture(),
    );
    expect(result.tradeCount, 1);
    expect(result.signalCount, 1);
    expect(result.totalNetPnl.isFinite, isTrue);
    expect(result.benchmarkHypotheticalPnl.isFinite, isTrue);
    expect(result.parametersFingerprint, matches(RegExp(r'^[a-f0-9]{64}$')));
    expect(result.resultFingerprint, matches(RegExp(r'^[a-f0-9]{64}$')));
    expect(result.warnings, isNotEmpty);
    expect(() => result.warnings.clear(), throwsUnsupportedError);
    expect(() => result.signals.clear(), throwsUnsupportedError);
  });

  test('parses actual backend open position without realizing its mark', () {
    final request =
        jsonDecode(rebound25OpenRequestFixture) as Map<String, dynamic>;
    final data =
        (jsonDecode(rebound25OpenResponseFixture)
                as Map<String, dynamic>)['data']
            as Map<String, dynamic>;
    final result = Rebound25ResearchResult.fromJson(data, request: request);
    expect(result.tradeCount, 0);
    expect(result.totalNetPnl, 0);
  });

  test('binds ISO Z requests to equivalent backend UTC-offset clocks', () {
    final request = requestFixture();
    for (final field in ['asOf', 'precommittedAt']) {
      request[field] = DateTime.parse(request[field] as String)
          .toUtc()
          .toIso8601String();
    }
    for (final bar in request['bars'] as List) {
      for (final field in ['openAt', 'observedAt', 'availableAt']) {
        bar[field] = DateTime.parse(bar[field] as String)
            .toUtc()
            .toIso8601String();
      }
    }
    expect(
      Rebound25ResearchResult.fromJson(
        dataFixture(),
        request: request,
      ).tradeCount,
      1,
    );
  });

  for (final field in [
    'productionEligible',
    'historicalPointInTimeEligible',
    'outOfSampleValidated',
    'automaticTrading',
    'ordersEnabled',
  ]) {
    test('refuses authority escalation $field', () {
      final data = dataFixture()..[field] = true;
      expect(
        () => Rebound25ResearchResult.fromJson(data, request: requestFixture()),
        throwsFormatException,
      );
    });
  }

  final corruptions = <String, void Function(Map<String, dynamic>)>{
    'real origin': (data) => data['evidenceKind'] = 'real',
    'advice': (data) => data['advisoryStatus'] = 'buy',
    'count': (data) => data['closedTradeCount'] = 2,
    'net PnL': (data) => data['totalNetPnl'] = 999,
    'hash': (data) => data['resultFingerprint'] = 'not-a-hash',
    'protocol': (data) => data['parameters']['order_units'] = 2,
    'instrument': (data) => data['instrumentId'] = 'OTHER',
    'cost': (data) => data['trades'][0]['commissionCost'] = -1,
    'trade PnL': (data) => data['trades'][0]['netPnl'] = 500,
    'exit reason': (data) =>
        data['trades'][0]['exitReason'] = 'unverified_sale',
    'benchmark PnL': (data) =>
        data['benchmark']['hypotheticalLiquidation']['netPnlAfterAllCosts'] =
            500,
    'benchmark realized': (data) =>
        data['benchmark']['hypotheticalLiquidation']['isRealized'] = true,
    'benchmark validated': (data) =>
        data['benchmark']['performanceValidated'] = true,
    'exposure comparability': (data) =>
        data['benchmarkComparison']['comparableByExposure'] = true,
    'outperformance': (data) =>
        data['benchmarkComparison']['outperformanceClaimed'] = true,
    'NaN': (data) => data['strategyAccounting']['realizedNetPnl'] = double.nan,
    'Infinity': (data) => data['benchmark']['lastMarkPrice'] = double.infinity,
  };
  for (final entry in corruptions.entries) {
    test('rejects corrupt report ${entry.key}', () {
      final data = dataFixture();
      entry.value(data);
      expect(
        () => Rebound25ResearchResult.fromJson(data, request: requestFixture()),
        throwsFormatException,
      );
    });
  }

  test('unauthenticated request never reaches HTTP', () async {
    final service = Rebound25ResearchService(
      session: session(authenticated: false),
      client: MockClient((_) async => fail('HTTP without authentication')),
    );
    await expectLater(service.run(requestFixture()), throwsStateError);
  });

  test(
    'posts frozen body with bearer; deduplicates and retries identical bytes',
    () async {
      final authority = session();
      final request = requestFixture();
      final pending = Completer<http.Response>();
      final bodies = <String>[];
      final service = Rebound25ResearchService(
        baseUrl: 'https://api.athena.test',
        session: authority,
        client: MockClient((call) async {
          expect(call.method, 'POST');
          expect(
            call.url.path,
            '/api/v1/research/strategies/rebound25/synthetic-backtest',
          );
          expect(call.headers['Authorization'], 'Bearer synthetic-owner-1');
          expect(call.followRedirects, isFalse);
          bodies.add(call.body);
          return bodies.length == 1
              ? pending.future
              : http.Response(rebound25ResponseFixture, 200);
        }),
      );
      final first = service.run(request);
      final duplicate = service.run(request);
      expect(identical(first, duplicate), isTrue);
      request['parameters']['commissionBps'] = 999;
      request['bars'][0]['close'] = 555;
      final failure = expectLater(first, throwsStateError);
      pending.complete(http.Response('synthetic-private-token', 503));
      await failure;
      await service.run(request);
      expect(bodies.length, 2);
      expect(bodies[0], bodies[1]);
      expect(jsonDecode(bodies.last)['parameters']['commissionBps'], 5);
      expect(jsonDecode(bodies.last)['bars'][0]['close'], 100);
    },
  );

  test('changed authority rejects a late response even with identical restored token', () async {
    final authority = session();
    final pending = Completer<http.Response>();
    final service = Rebound25ResearchService(
      session: authority,
      client: MockClient((_) => pending.future),
    );
    final result = service.run(requestFixture());
    final assertion = expectLater(result, throwsStateError);
    authority.clear();
    login(authority, 1);
    pending.complete(http.Response(rebound25ResponseFixture, 200));
    await assertion;
  });

  for (final code in [401, 403, 302, 503]) {
    test(
      'no public/provider fallback and no raw body leakage for HTTP $code',
      () async {
        var calls = 0;
        final service = Rebound25ResearchService(
          session: session(),
          client: MockClient((_) async {
            calls++;
            return http.Response('synthetic-private-token', code);
          }),
        );
        try {
          await service.run(requestFixture());
          fail('expected rejection');
        } catch (error) {
          expect(error.toString(), isNot(contains('synthetic-private-token')));
        }
        expect(calls, 1);
      },
    );
  }

  test('timeout and oversized response cannot produce a result', () async {
    final never = Completer<http.Response>();
    final timed = Rebound25ResearchService(
      session: session(),
      requestTimeout: const Duration(milliseconds: 5),
      client: MockClient((_) => never.future),
    );
    await expectLater(timed.run(requestFixture()), throwsStateError);
    never.complete(http.Response(rebound25ResponseFixture, 200));
    final large = Rebound25ResearchService(
      session: session(),
      client: MockClient(
        (_) async => http.Response(
          'x' * (Rebound25ResearchService.maxBodyBytes + 1),
          200,
        ),
      ),
    );
    await expectLater(large.run(requestFixture()), throwsStateError);
  });

  test(
    'request cannot coerce real data, authority or non-JSON parameters',
    () async {
      for (final mutate in <void Function(Map<String, dynamic>)>[
        (body) => body['evidenceKind'] = 'real',
        (body) => body['ordersEnabled'] = true,
        (body) => body['parameters']['orderUnits'] = '1',
        (body) => body['parameters']['commissionBps'] = double.nan,
        (body) => body['bars'][0]['availableAt'] = '2026-01-01T18:00:00',
      ]) {
        final body = requestFixture();
        mutate(body);
        final service = Rebound25ResearchService(
          session: session(),
          client: MockClient((_) async => fail('invalid HTTP')),
        );
        await expectLater(service.run(body), throwsFormatException);
      }
    },
  );
}
