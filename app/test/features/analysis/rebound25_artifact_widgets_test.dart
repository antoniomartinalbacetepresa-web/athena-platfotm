import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/presentation/widgets/rebound25_artifact_history_panel.dart';
import 'package:app/features/analysis/presentation/widgets/rebound25_research_panel.dart';
import 'package:app/features/analysis/services/rebound25_artifact_service.dart';
import 'package:app/features/analysis/services/rebound25_research_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../fixtures/rebound25_artifact_fixture.dart';

Rebound25Artifact _artifact() {
  final data =
      (jsonDecode(rebound25ArtifactFixture) as Map<String, dynamic>)['data']
          as Map<String, dynamic>;
  return Rebound25Artifact(
    artifactHash: data['artifactHash'] as String,
    createdAt: DateTime.parse(data['createdAt'] as String),
    result: Rebound25ResearchResult.fromJson(
      data['result'] as Map<String, dynamic>,
      request: data['request'] as Map<String, dynamic>,
    ),
  );
}

class _Artifacts extends Rebound25ArtifactService {
  int lists = 0, gets = 0, saves = 0;
  bool failList = false;
  Future<Rebound25Artifact>? pendingGet;
  Future<Rebound25Artifact>? pendingSave;
  @override
  Future<List<Rebound25ArtifactEntry>> list() async {
    lists++;
    if (failList) {
      failList = false;
      throw StateError('Synthetic interruption');
    }
    return [_artifact()];
  }

  @override
  Future<Rebound25Artifact> get(String hash) {
    gets++;
    expect(hash, _artifact().artifactHash);
    return pendingGet ?? Future.value(_artifact());
  }

  @override
  Future<Rebound25Artifact> save(
    Map<String, dynamic> request, {
    required String expectedResultFingerprint,
  }) {
    saves++;
    expect(expectedResultFingerprint, _artifact().result.resultFingerprint);
    return pendingSave ?? Future.value(_artifact());
  }
}

class _Research extends Rebound25ResearchService {
  @override
  Future<Rebound25ResearchResult> run(Map<String, dynamic> request) async =>
      _artifact().result;
}

void _owner(int id) {
  final now = DateTime.now().toUtc();
  AuthSession.instance.establish(
    accessToken: 'synthetic-$id',
    account: AuthAccount(
      id: id,
      email: '$id@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

Widget _surface(Widget child) => MaterialApp(
  home: Scaffold(body: SingleChildScrollView(child: child)),
);
Future<void> _tap(WidgetTester tester, Key key) async {
  final finder = find.byKey(key);
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pump();
}

void main() {
  setUp(() => AuthSession.instance.clear());
  tearDown(() => AuthSession.instance.clear());
  testWidgets(
    'guest cannot read private artifacts and opening the surface never loads automatically',
    (tester) async {
      final service = _Artifacts();
      await tester.pumpWidget(
        _surface(Rebound25ArtifactHistoryPanel(service: service)),
      );
      expect(
        find.byKey(const Key('rebound25-artifact-auth-required')),
        findsOneWidget,
      );
      expect(service.lists, 0);
      expect(service.gets, 0);
      service.dispose();
    },
  );
  testWidgets(
    'explicit private history loading and opening displays separate simulated accounting',
    (tester) async {
      _owner(1);
      final service = _Artifacts();
      await tester.pumpWidget(
        _surface(Rebound25ArtifactHistoryPanel(service: service)),
      );
      expect(service.lists, 0);
      await _tap(tester, const Key('rebound25-artifact-history-load'));
      await tester.pumpAndSettle();
      await _tap(
        tester,
        ValueKey('rebound25-artifact-open-${_artifact().artifactHash}'),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('rebound25-artifact-detail')),
        findsOneWidget,
      );
      expect(find.textContaining('no existía en el corte'), findsOneWidget);
      expect(find.textContaining('separada de tus posiciones'), findsOneWidget);
      expect(find.textContaining('PnL simulado'), findsOneWidget);
      expect(service.gets, 1);
      service.dispose();
    },
  );
  testWidgets(
    'private index failure is visible and can be retried without Portfolio writes',
    (tester) async {
      _owner(1);
      final service = _Artifacts()..failList = true;
      await tester.pumpWidget(
        _surface(Rebound25ArtifactHistoryPanel(service: service)),
      );
      await _tap(tester, const Key('rebound25-artifact-history-load'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('rebound25-artifact-error')), findsOneWidget);
      await _tap(tester, const Key('rebound25-artifact-history-load'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('rebound25-artifact-error')), findsNothing);
      expect(service.lists, 2);
      expect(service.saves, 0);
      service.dispose();
    },
  );
  testWidgets('account changes discard late private artifact detail', (
    tester,
  ) async {
    _owner(1);
    final service = _Artifacts();
    final pending = Completer<Rebound25Artifact>();
    service.pendingGet = pending.future;
    await tester.pumpWidget(
      _surface(Rebound25ArtifactHistoryPanel(service: service)),
    );
    await _tap(tester, const Key('rebound25-artifact-history-load'));
    await tester.pumpAndSettle();
    await _tap(
      tester,
      ValueKey('rebound25-artifact-open-${_artifact().artifactHash}'),
    );
    _owner(2);
    await tester.pump();
    pending.complete(_artifact());
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rebound25-artifact-detail')), findsNothing);
    expect(
      find.byKey(
        ValueKey('rebound25-artifact-open-${_artifact().artifactHash}'),
      ),
      findsNothing,
    );
    service.dispose();
  });
  testWidgets('Lab persistence is explicit and blocks duplicate saves', (
    tester,
  ) async {
    _owner(1);
    final service = _Artifacts();
    final research = _Research();
    final pending = Completer<Rebound25Artifact>();
    service.pendingSave = pending.future;
    await tester.pumpWidget(
      _surface(
        Rebound25ResearchPanel(service: research, artifactService: service),
      ),
    );
    await _tap(tester, const Key('rebound25-run'));
    await tester.pumpAndSettle();
    expect(service.saves, 0);
    await _tap(tester, const Key('rebound25-artifact-save'));
    await _tap(tester, const Key('rebound25-artifact-save'));
    expect(service.saves, 1);
    pending.complete(_artifact());
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rebound25-artifact-saved')), findsOneWidget);
    expect(service.lists, 0);
    service.dispose();
    research.dispose();
  });
  testWidgets('late save result is hidden after changing account', (
    tester,
  ) async {
    _owner(1);
    final service = _Artifacts();
    final research = _Research();
    final pending = Completer<Rebound25Artifact>();
    service.pendingSave = pending.future;
    await tester.pumpWidget(
      _surface(
        Rebound25ResearchPanel(service: research, artifactService: service),
      ),
    );
    await _tap(tester, const Key('rebound25-run'));
    await tester.pumpAndSettle();
    await _tap(tester, const Key('rebound25-artifact-save'));
    _owner(2);
    await tester.pump();
    pending.complete(_artifact());
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('rebound25-artifact-saved')), findsNothing);
    service.dispose();
    research.dispose();
  });
}
