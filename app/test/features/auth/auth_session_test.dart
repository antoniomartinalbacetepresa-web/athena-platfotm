import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final now = DateTime.utc(2026, 9, 11);
  AuthAccount account({bool active = true, int id = 7, String email = 'owner@example.com'}) => AuthAccount(
        id: id,
        email: email,
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

  test('authority transitions notify observers without duplicate no-op clears', () async {
    final store = _FakeAuthTokenStore();
    final session = AuthSession.forTesting(store);
    var notifications = 0;
    session.addListener(() => notifications += 1);

    session.establish(accessToken: 'token-123', account: account());
    expect(notifications, 1);
    expect(session.isAuthenticated, isTrue);

    await session.clearPersisted();
    expect(notifications, 2);
    expect(session.isAuthenticated, isFalse);

    await session.clearPersisted();
    expect(notifications, 2);
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

  test('stale restore cannot overwrite a newer authenticated authority', () async {
    final store = _FakeAuthTokenStore(token: 'stored-owner-a');
    final session = AuthSession.forTesting(store);
    final validation = Completer<AuthAccount>();

    final restoring = session.restore(
      validateToken: (token) {
        expect(token, 'stored-owner-a');
        return validation.future;
      },
      shouldDiscardToken: (_) => false,
    );
    await Future<void>.delayed(Duration.zero);

    final replacement = account(id: 23, email: 'owner-b@example.com');
    session.establish(accessToken: 'owner-b-token', account: replacement);
    validation.complete(account());

    final result = await restoring;
    expect(result, AuthSessionRestoreResult.restored);
    expect(session.accessToken, 'owner-b-token');
    expect(session.account?.id, 23);
    expect(session.account?.email, 'owner-b@example.com');
  });

  test('restore normalizes persisted token before remote validation', () async {
    final store = _FakeAuthTokenStore(token: '  stored-token  ');
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
    expect(session.accessToken, 'stored-token');
  });

  test('blank persisted token is deleted without reaching remote validation', () async {
    final store = _FakeAuthTokenStore(token: '   ');
    final session = AuthSession.forTesting(store);
    var validationCalls = 0;

    final result = await session.restore(
      validateToken: (_) async {
        validationCalls += 1;
        return account();
      },
      shouldDiscardToken: (_) => false,
    );

    expect(result, AuthSessionRestoreResult.rejected);
    expect(validationCalls, 0);
    expect(store.token, isNull);
    expect(session.isAuthenticated, isFalse);
  });

  test('blank persisted token stays fail closed when secure deletion fails', () async {
    final store = _FakeAuthTokenStore(token: '   ', failDeletes: true);
    final session = AuthSession.forTesting(store);
    var validationCalls = 0;

    final result = await session.restore(
      validateToken: (_) async {
        validationCalls += 1;
        return account();
      },
      shouldDiscardToken: (_) => false,
    );

    expect(result, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(validationCalls, 0);
    expect(store.token, '   ');
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
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

  test('clearPersisted revokes memory authority even when secure deletion fails',
      () async {
    final store = _FakeAuthTokenStore(token: 'token-123', failDeletes: true);
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'token-123', account: account());

    await expectLater(session.clearPersisted(), throwsStateError);

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
    expect(store.token, 'token-123');
  });

  test(
      'remote invalidation stays fail closed across restart when secure deletion fails',
      () async {
    final store = _FakeAuthTokenStore(token: 'server-revoked-token', failDeletes: true);
    final session = AuthSession.forTesting(store);
    session.establish(accessToken: 'server-revoked-token', account: account());

    final deleted = await session.clearAfterRemoteInvalidation();

    expect(deleted, isFalse);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.token, 'server-revoked-token');

    final restarted = AuthSession.forTesting(store);
    var validationCalls = 0;
    final restored = await restarted.restore(
      validateToken: (token) async {
        validationCalls += 1;
        expect(token, 'server-revoked-token');
        throw const _RejectedSession();
      },
      shouldDiscardToken: (error) => error is _RejectedSession,
    );

    expect(validationCalls, 1);
    expect(restored, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(restarted.isAuthenticated, isFalse);
    expect(restarted.accessToken, isNull);
    expect(store.token, 'server-revoked-token');
  });
}

class _RejectedSession implements Exception {
  const _RejectedSession();
}

class _FakeAuthTokenStore implements AuthTokenStore {
  _FakeAuthTokenStore({
    this.token,
    this.failWrites = false,
    this.failDeletes = false,
  });

  String? token;
  final bool failWrites;
  final bool failDeletes;

  @override
  Future<void> deleteAccessToken() async {
    if (failDeletes) throw StateError('secure storage unavailable');
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
