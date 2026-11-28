import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/services/rebound25_artifact_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../../fixtures/rebound25_artifact_fixture.dart';

class _Store implements AuthTokenStore {
  @override
  Future<String?> readAccessToken() async => null;
  @override
  Future<void> writeAccessToken(String token) async {}
  @override
  Future<void> deleteAccessToken() async {}
}

void _owner(AuthSession session, int id) {
  final now = DateTime.now().toUtc();
  session.establish(
    accessToken: 'fixture-$id',
    account: AuthAccount(
      id: id,
      email: '$id@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

Map<String, dynamic> _data() =>
    (jsonDecode(rebound25ArtifactFixture) as Map<String, dynamic>)['data']
        as Map<String, dynamic>;
String _fingerprint(Map<String, dynamic> data) =>
    (data['result'] as Map)['resultFingerprint'] as String;
http.Response _response(Map<String, dynamic> data) =>
    http.Response(jsonEncode({'data': data}), 200);
Map<String, dynamic> _index(Map<String, dynamic> detail) => {
  ...detail,
  'metadataOnly': true,
  'readOnly': true,
  'returnedCount': 1,
  'items': [
    {
      'artifactHash': detail['artifactHash'],
      'fixtureId': detail['fixtureId'],
      'createdAt': detail['createdAt'],
    },
  ],
};
void main() {
  test('anonymous save and list fail before HTTP', () async {
    var calls = 0;
    final client = MockClient((_) async {
      calls++;
      return http.Response('{}', 200);
    });
    final service = Rebound25ArtifactService(
      client: client,
      session: AuthSession.forTesting(_Store()),
    );
    await expectLater(service.list(), throwsStateError);
    await expectLater(
      service.save(
        _data()['request'] as Map<String, dynamic>,
        expectedResultFingerprint: _fingerprint(_data()),
      ),
      throwsStateError,
    );
    expect(calls, 0);
    client.close();
  });
  test('save sends parameters only, coalesces concurrent calls and retrieves private artifact', () async {
    final session = AuthSession.forTesting(_Store());
    _owner(session, 1);
    final data = _data(), pending = Completer<http.Response>();
    final calls = <String>[];
    final client = MockClient((request) async {
      calls.add(request.method);
      expect(request.headers['Authorization'], 'Bearer fixture-1');
      if (request.method == 'POST') {
        expect(
          request.url.path,
          '/api/v1/research/strategies/rebound25/artifacts',
        );
        final body = jsonDecode(request.body) as Map;
        expect(body.keys.toSet(), {'fixtureId', 'parameters'});
        expect(body['fixtureId'], rebound25ServerFixtureId);
        return pending.future;
      }
      expect(request.url.path, endsWith('/${data['artifactHash']}'));
      return _response(data);
    });
    final service = Rebound25ArtifactService(client: client, session: session);
    final request = data['request'] as Map<String, dynamic>;
    final first = service.save(
      request,
      expectedResultFingerprint: _fingerprint(data),
    );
    final second = service.save(
      request,
      expectedResultFingerprint: _fingerprint(data),
    );
    expect(identical(first, second), true);
    pending.complete(_response(data));
    final saved = await first;
    await second;
    expect(saved.artifactHash, data['artifactHash']);
    expect(saved.result.resultFingerprint, _fingerprint(data));
    expect(calls, ['POST', 'GET']);
    client.close();
  });
  test('uncertain retry preserves the original parameter body despite caller mutation', () async {
    final session = AuthSession.forTesting(_Store());
    _owner(session, 1);
    final data = _data();
    final bodies = <String>[];
    final client = MockClient((request) async {
      if (request.method == 'GET') return _response(data);
      bodies.add(request.body);
      if (bodies.length == 1) {
        throw http.ClientException('Synthetic interruption');
      }
      return _response(data);
    });
    final service = Rebound25ArtifactService(client: client, session: session);
    final request = data['request'] as Map<String, dynamic>;
    final expected = _fingerprint(data);
    await expectLater(
      service.save(request, expectedResultFingerprint: expected),
      throwsA(isA<http.ClientException>()),
    );
    (request['parameters'] as Map)['takeProfitPct'] = 25;
    // GET uses independently regenerated fixture data, not the caller's mutable object.
    final original = _data();
    // Restore the response object while preserving the caller Map identity.
    data['request'] = original['request'];
    await service.save(request, expectedResultFingerprint: expected);
    expect(bodies[0], bodies[1]);
    client.close();
  });
  test(
    'owner switch during save rejects response before private retrieval',
    () async {
      final session = AuthSession.forTesting(_Store());
      _owner(session, 1);
      final data = _data(), pending = Completer<http.Response>();
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return pending.future;
      });
      final service = Rebound25ArtifactService(
        client: client,
        session: session,
      );
      final future = service.save(
        data['request'] as Map<String, dynamic>,
        expectedResultFingerprint: _fingerprint(data),
      );
      _owner(session, 2);
      pending.complete(_response(data));
      await expectLater(future, throwsStateError);
      expect(calls, 1);
      client.close();
    },
  );
  test(
    'a saved result cannot be mislabeled as a different reviewed calculation',
    () async {
      final session = AuthSession.forTesting(_Store());
      _owner(session, 1);
      final data = _data();
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return _response(data);
      });
      final service = Rebound25ArtifactService(
        client: client,
        session: session,
      );
      await expectLater(
        service.save(
          data['request'] as Map<String, dynamic>,
          expectedResultFingerprint: 'f' * 64,
        ),
        throwsFormatException,
      );
      expect(calls, 1);
      client.close();
    },
  );
  for (final defect in [
    'license',
    'orders',
    'fixture',
    'time',
    'generated',
    'hash',
  ]) {
    test('private detail rejects incompatible artifact: $defect', () async {
      final session = AuthSession.forTesting(_Store());
      _owner(session, 1);
      final data = _data(), hash = data['artifactHash'] as String;
      if (defect == 'license') data['licenseVerified'] = true;
      if (defect == 'orders') data['ordersEnabled'] = true;
      if (defect == 'fixture') data['fixtureId'] = 'real-provider';
      if (defect == 'time') data['createdAt'] = '2026-02-30T12:00:00Z';
      if (defect == 'generated') data['serverFixtureGenerated'] = false;
      if (defect == 'hash') data['artifactHash'] = 'a' * 64;
      final client = MockClient((_) async => _response(data));
      final service = Rebound25ArtifactService(
        client: client,
        session: session,
      );
      await expectLater(service.get(hash), throwsFormatException);
      client.close();
    });
  }
  test('owned index rejects duplicate identities', () async {
    final session = AuthSession.forTesting(_Store());
    _owner(session, 1);
    final data = _index(_data());
    (data['items'] as List).add((data['items'] as List).first);
    data['returnedCount'] = 2;
    final client = MockClient((_) async => _response(data));
    final service = Rebound25ArtifactService(client: client, session: session);
    await expectLater(service.list(), throwsFormatException);
    client.close();
  });
  for (final status in [401, 403, 404, 503]) {
    test('HTTP $status has no public fallback', () async {
      final session = AuthSession.forTesting(_Store());
      _owner(session, 1);
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return http.Response('{}', status);
      });
      final service = Rebound25ArtifactService(
        client: client,
        session: session,
      );
      await expectLater(
        service.get(_data()['artifactHash'] as String),
        throwsStateError,
      );
      expect(calls, 1);
      client.close();
    });
  }
}
