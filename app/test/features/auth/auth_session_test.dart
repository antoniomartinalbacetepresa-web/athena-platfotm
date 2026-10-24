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

  test('logout deletion finishing during a new login write is repaired', () async {
    final store = _WriteCompletesAfterDeletionStore();
    final session = AuthSession.forTesting(store);

    session.clear();
    await store.deleteStarted.future;
    final loggingIn = session.establishPersisted(
      accessToken: 'replacement-token',
      account: account(id: 23, email: 'replacement@example.com'),
    );
    await store.firstWriteStarted.future;
    expect(session.isAuthenticated, isFalse);

    // The write already changed secure storage, but its Future is pending.
    // The older logout deletes that token without observing new authority.
    store.releaseDelete.complete();
    await store.deleteCompleted.future;
    expect(store.token, isNull);

    store.releaseFirstWrite.complete();
    await loggingIn;
    expect(store.token, 'replacement-token');
    expect(store.writeCount, 2);
    expect(session.account?.id, 23);
    expect(session.accessToken, 'replacement-token');
  });

  test('secure read-back failure does not expose authenticated authority', () async {
    final store = _FakeAuthTokenStore(failReads: true);
    final session = AuthSession.forTesting(store);

    await expectLater(
      session.establishPersisted(
        accessToken: 'unverified-token',
        account: account(),
      ),
      throwsStateError,
    );
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
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

  test('restore refuses a token while an earlier logout deletion is pending',
      () async {
    final store = _FirstDeleteDelayedAuthTokenStore(token: 'stored-token');
    final session = AuthSession.forTesting(store);
    session.clear();
    await store.firstDeleteStarted.future;

    var validations = 0;
    final result = await session.restore(
      validateToken: (_) async {
        validations += 1;
        return account();
      },
      shouldDiscardToken: (_) => false,
    );

    expect(result, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(validations, 0);
    expect(session.isAuthenticated, isFalse);
    store.releaseFirstDelete.complete();
    await Future<void>.delayed(Duration.zero);
    expect(store.token, isNull);
  });

  test('restore refuses a credential removed during remote validation',
      () async {
    final store = _FakeAuthTokenStore(token: 'stored-token');
    final session = AuthSession.forTesting(store);
    final validation = Completer<AuthAccount>();

    final restoring = session.restore(
      validateToken: (token) {
        expect(token, 'stored-token');
        return validation.future;
      },
      shouldDiscardToken: (_) => false,
    );
    await Future<void>.delayed(Duration.zero);
    store.token = null;
    validation.complete(account());

    expect(await restoring, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
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

  test('delayed secure write after logout cannot restore session authority', () async {
    final store = _DelayedWriteAuthTokenStore();
    final session = AuthSession.forTesting(store);
    final pending = session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    session.clear();
    expect(session.isAuthenticated, isFalse);
    store.releaseWrite.complete();

    await expectLater(pending, throwsStateError);
    expect(session.accessToken, isNull);
    expect(session.account, isNull);
    expect(store.token, isNull);
  });

  test('delayed secure write after persisted logout is cleaned up', () async {
    final store = _DelayedWriteAuthTokenStore();
    final session = AuthSession.forTesting(store);
    final pending = session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    await session.clearPersisted();
    store.releaseWrite.complete();

    await expectLater(pending, throwsStateError);
    expect(session.isAuthenticated, isFalse);
    expect(store.token, isNull);
  });

  test('late old-owner write repairs newer owner secure credential', () async {
    final store = _FirstWriteDelayedAuthTokenStore();
    final session = AuthSession.forTesting(store);

    final oldLogin = session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    expect(store.token, 'new-owner-token');
    expect(session.account?.id, 23);

    store.releaseFirstWrite.complete();
    await expectLater(oldLogin, throwsStateError);

    expect(session.isAuthenticated, isTrue);
    expect(session.accessToken, 'new-owner-token');
    expect(session.account?.id, 23);
    expect(store.token, 'new-owner-token');
  });

  test('logout during stale-write repair removes durable credential', () async {
    final store = _FirstWriteDelayedAuthTokenStore(delayRepair: true);
    final session = AuthSession.forTesting(store);
    final oldLogin = session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );
    final rejection = expectLater(oldLogin, throwsStateError);
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );

    store.releaseFirstWrite.complete();
    await store.repairStarted.future;
    session.clear();
    expect(session.isAuthenticated, isFalse);
    store.releaseRepair.complete();
    await rejection;

    expect(session.accessToken, isNull);
    expect(store.token, isNull);
  });

  test('blank stored-token deletion cannot erase a newer login', () async {
    final store = _FirstDeleteDelayedAuthTokenStore(token: '   ');
    final session = AuthSession.forTesting(store);
    final restoring = session.restore(
      validateToken: (_) async => throw StateError('must not validate blank'),
      shouldDiscardToken: (_) => true,
    );
    await store.firstDeleteStarted.future;

    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();

    expect(await restoring, AuthSessionRestoreResult.restored);
    expect(session.account?.id, 23);
    expect(session.accessToken, 'new-owner-token');
    expect(store.token, 'new-owner-token');
  });

  test('rejected stored-token deletion cannot erase a newer login', () async {
    final store = _FirstDeleteDelayedAuthTokenStore(token: 'revoked-token');
    final session = AuthSession.forTesting(store);
    final restoring = session.restore(
      validateToken: (_) async => throw const _RejectedSession(),
      shouldDiscardToken: (error) => error is _RejectedSession,
    );
    await store.firstDeleteStarted.future;

    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();

    expect(await restoring, AuthSessionRestoreResult.restored);
    expect(session.account?.id, 23);
    expect(session.accessToken, 'new-owner-token');
    expect(store.token, 'new-owner-token');
  });

  test('failed restore-deletion repair revokes newer memory authority', () async {
    final store = _FirstDeleteDelayedAuthTokenStore(
      token: 'revoked-token',
      failRepairWrites: true,
    );
    final session = AuthSession.forTesting(store);
    final restoring = session.restore(
      validateToken: (_) async => throw const _RejectedSession(),
      shouldDiscardToken: (error) => error is _RejectedSession,
    );
    await store.firstDeleteStarted.future;

    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();

    expect(await restoring, AuthSessionRestoreResult.temporarilyUnavailable);
    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.token, isNull);
  });

  test('delayed clear deletion cannot erase a newer owner credential', () async {
    final store = _FirstDeleteDelayedAuthTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    session.clear();
    await store.firstDeleteStarted.future;
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();
    await Future<void>.delayed(Duration.zero);

    expect(session.account?.id, 23);
    expect(session.accessToken, 'new-owner-token');
    expect(store.token, 'new-owner-token');
  });

  test('delayed clearPersisted deletion preserves newer owner', () async {
    final store = _FirstDeleteDelayedAuthTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    final oldLogout = session.clearPersisted();
    await store.firstDeleteStarted.future;
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();
    await oldLogout;

    expect(session.account?.id, 23);
    expect(session.accessToken, 'new-owner-token');
    expect(store.token, 'new-owner-token');
  });

  test('delayed remote invalidation cannot erase replacement owner', () async {
    final store = _FirstDeleteDelayedAuthTokenStore();
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    final invalidating = session.clearAfterRemoteInvalidationIfCurrent(
      'old-owner-token',
    );
    await store.firstDeleteStarted.future;
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();
    expect(await invalidating, isTrue);

    expect(session.account?.id, 23);
    expect(session.accessToken, 'new-owner-token');
    expect(store.token, 'new-owner-token');
  });

  test('logout during delayed deletion repair clears both authorities', () async {
    final store = _FirstDeleteDelayedAuthTokenStore(delayRepair: true);
    final session = AuthSession.forTesting(store);
    await session.establishPersisted(
      accessToken: 'old-owner-token',
      account: account(),
    );

    final oldLogout = session.clearPersisted();
    await store.firstDeleteStarted.future;
    await session.establishPersisted(
      accessToken: 'new-owner-token',
      account: account(id: 23, email: 'new-owner@example.com'),
    );
    store.releaseFirstDelete.complete();
    await store.repairStarted.future;
    session.clear();
    store.releaseRepair.complete();
    await oldLogout;

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.token, isNull);
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
    this.failReads = false,
  });

  String? token;
  final bool failWrites;
  final bool failDeletes;
  final bool failReads;

  @override
  Future<void> deleteAccessToken() async {
    if (failDeletes) throw StateError('secure storage unavailable');
    token = null;
  }

  @override
  Future<String?> readAccessToken() async {
    if (failReads) throw StateError('secure storage read unavailable');
    return token;
  }

  @override
  Future<void> writeAccessToken(String token) async {
    if (failWrites) throw StateError('secure storage unavailable');
    this.token = token;
  }
}

class _WriteCompletesAfterDeletionStore implements AuthTokenStore {
  final Completer<void> deleteStarted = Completer<void>();
  final Completer<void> releaseDelete = Completer<void>();
  final Completer<void> deleteCompleted = Completer<void>();
  final Completer<void> firstWriteStarted = Completer<void>();
  final Completer<void> releaseFirstWrite = Completer<void>();
  String? token;
  int writeCount = 0;

  @override
  Future<void> deleteAccessToken() async {
    deleteStarted.complete();
    await releaseDelete.future;
    token = null;
    deleteCompleted.complete();
  }

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String value) async {
    writeCount += 1;
    token = value;
    if (writeCount == 1) {
      firstWriteStarted.complete();
      await releaseFirstWrite.future;
    }
  }
}

class _DelayedWriteAuthTokenStore implements AuthTokenStore {
  final Completer<void> releaseWrite = Completer<void>();
  String? token;

  @override
  Future<void> writeAccessToken(String value) async {
    await releaseWrite.future;
    token = value;
  }

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> deleteAccessToken() async {
    token = null;
  }
}

class _FirstWriteDelayedAuthTokenStore implements AuthTokenStore {
  _FirstWriteDelayedAuthTokenStore({this.delayRepair = false});

  final bool delayRepair;
  final Completer<void> releaseFirstWrite = Completer<void>();
  final Completer<void> repairStarted = Completer<void>();
  final Completer<void> releaseRepair = Completer<void>();
  String? token;
  int _writes = 0;

  @override
  Future<void> writeAccessToken(String value) async {
    _writes += 1;
    if (_writes == 1) {
      await releaseFirstWrite.future;
    }
    if (_writes == 3 && delayRepair) {
      repairStarted.complete();
      await releaseRepair.future;
    }
    token = value;
  }

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> deleteAccessToken() async {
    token = null;
  }
}

class _FirstDeleteDelayedAuthTokenStore implements AuthTokenStore {
  _FirstDeleteDelayedAuthTokenStore({
    this.delayRepair = false,
    this.failRepairWrites = false,
    this.token,
  });

  final bool delayRepair;
  final bool failRepairWrites;
  final Completer<void> firstDeleteStarted = Completer<void>();
  final Completer<void> releaseFirstDelete = Completer<void>();
  final Completer<void> repairStarted = Completer<void>();
  final Completer<void> releaseRepair = Completer<void>();
  String? token;
  int _deletes = 0;
  int _writes = 0;

  @override
  Future<void> deleteAccessToken() async {
    _deletes += 1;
    if (_deletes == 1) {
      firstDeleteStarted.complete();
      await releaseFirstDelete.future;
    }
    token = null;
  }

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String value) async {
    _writes += 1;
    if (_writes == 3 && delayRepair) {
      repairStarted.complete();
      await releaseRepair.future;
    }
    if (_writes == 2 && failRepairWrites) {
      throw StateError('secure storage repair unavailable');
    }
    token = value;
  }
}
