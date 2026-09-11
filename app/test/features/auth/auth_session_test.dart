import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final now = DateTime.utc(2026, 9, 11);
  AuthAccount account({bool active = true}) => AuthAccount(
        id: 7,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: active,
        createdAt: now,
        updatedAt: now,
      );

  test('establishPersisted writes token before exposing authenticated state', () async {
    final store = _FakeAuthTokenStore();
    final session = AuthSession.forTesting(store);

    await session.establishPersisted(
      accessToken: ' token-123 ',
      account: account(),
    );

    expect(store.token, 'token-123');
    expect(session.accessToken, 'token-123');
    expect(session.account?.id, 7);
    expect(session.isAuthenticated, isTrue);
  });

  test('persistence failure fails closed and never exposes session in memory', () async {
    final store = _FakeAuthTokenStore(failWrites: true);
    final session = AuthSession.forTesting(store);

    await expectLater(
      session.establishPersisted(
        accessToken: 'token-123',
        account: account(),
      ),
      throwsStateError,
    );

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
  });

  test('restore validates stored token before authenticating', () async {
    final store = _FakeAuthTokenStore(token: 'stored-token');
    final session = AuthSession.forTesting(store);
    var validatedToken = '';

    final result = await session.restore(
      validateToken: (token) async {
        validatedToken = token;
        return account();
      },
      shouldDiscardToken: (_) => false,
    );

    expect(result, AuthSessionRestoreResult.restored);
    expect(validatedToken, 'stored-token');
    expect(session.isAuthenticated, isTrue);
  });

  test('server-rejected stored token is deleted and never restored', () async {
    final store = _FakeAuthTokenStore(token: 'revoked-token');
    final session = AuthSession.forTesting(store);

    final result = await session.restore(
      validateToken: (_) async => throw const _RejectedSession(),
      shouldDiscardToken: (error) => error is _RejectedSession,
    );

    expect(result, AuthSessionRestoreResult.rejected);
    expect(store.token, isNull);
    expect(session.isAuthenticated, isFalse);
  });

  test('transient validation failure preserves token but does not authenticate', () async {
    final store = _FakeAuthTokenStore(token: 'possibly-valid-token');
    final session = AuthSession.forTesting(store);

    final result = await session.restore(
      validateToken: (_) async => throw StateError('network unavailable'),
      shouldDiscardToken: (_) => false,
    );

    expect(result, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(store.token, 'possibly-valid-token');
    expect(session.isAuthenticated, isFalse);
  });

  test('clearPersisted removes durable token and authenticated memory state', () async {
    final store = _FakeAuthTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'token-123',
      account: account(),
    );

    await session.clearPersisted();

    expect(store.token, isNull);
    expect(session.isAuthenticated, isFalse);
  });
}

class _RejectedSession implements Exception {
  const _RejectedSession();
}

class _FakeAuthTokenStore implements AuthTokenStore {
  _FakeAuthTokenStore({this.token, this.failWrites = false});

  String? token;
  final bool failWrites;

  @override
  Future<void> deleteAccessToken() async {
    token = null;
  }

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String token) async {
    if (failWrites) throw StateError('secure storage unavailable');
    this.token = token;
  }
}
