import 'dart:async';
import 'dart:convert';

import 'package:app/features/analysis/presentation/widgets/rebound25_artifact_review_form.dart';
import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/analysis/services/rebound25_artifact_review_service.dart';
import 'package:app/features/analysis/services/rebound25_artifact_service.dart';
import 'package:app/features/analysis/services/rebound25_research_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import '../../fixtures/rebound25_artifact_fixture.dart';

Rebound25Artifact _artifact({String? hash, DateTime? createdAt}) {
  final data =
      (jsonDecode(rebound25ArtifactFixture) as Map<String, dynamic>)['data']
          as Map<String, dynamic>;
  return Rebound25Artifact(
    artifactHash: hash ?? data['artifactHash'] as String,
    createdAt: createdAt ?? DateTime.parse(data['createdAt'] as String),
    result: Rebound25ResearchResult.fromJson(
      data['result'] as Map<String, dynamic>,
      request: data['request'] as Map<String, dynamic>,
    ),
  );
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

Rebound25ArtifactReviewDraft _draft({Rebound25Artifact? artifact}) =>
    Rebound25ArtifactReviewDraft(
      artifact: artifact ?? _artifact(),
      thesis: 'Pregunta humana',
      objection: 'Costes y sesgo de selección',
      authoredAt: DateTime.now().toUtc(),
    );

class _Review extends Rebound25ArtifactReviewService {
  final drafts = <Rebound25ArtifactReviewDraft>[];
  bool fail = false;
  Future<PrivateResearchCycleDetail>? pending;
  @override
  Future<PrivateResearchCycleDetail> create(
    Rebound25ArtifactReviewDraft draft,
  ) async {
    drafts.add(draft);
    if (fail) {
      fail = false;
      throw StateError('Synthetic interruption');
    }
    return pending ??
        PrivateResearchCycleDetail(
          symbol: 'SYNTH',
          cycleHash: 'a' * 64,
          asOf: draft.asOf,
        );
  }
}

Widget _surface(Widget child) => MaterialApp(
  home: Scaffold(body: SingleChildScrollView(child: child)),
);
Future<void> _tap(WidgetTester tester, String key) async {
  final finder = find.byKey(Key(key));
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pump();
}

Future<void> _fill(WidgetTester tester) async {
  await tester.enterText(
    find.byKey(const Key('rebound25-review-thesis')),
    'Hipótesis humana',
  );
  await tester.enterText(
    find.byKey(const Key('rebound25-review-objection')),
    'Objeción material',
  );
  await _tap(tester, 'rebound25-review-confirm');
}

void main() {
  setUp(() => AuthSession.instance.clear());
  tearDown(() => AuthSession.instance.clear());
  test('draft rejects invalid identity before substring and impossible availability', () {
    expect(() => _draft(artifact: _artifact(hash: 'x')), throwsFormatException);
    expect(
      () => _draft(
        artifact: _artifact(
          createdAt: DateTime.now().toUtc().add(const Duration(days: 1)),
        ),
      ),
      throwsFormatException,
    );
    final draft = _draft();
    final body = jsonDecode(draft.encodedBody) as Map;
    expect(body['thesis'], 'Pregunta humana');
    expect(body['asOf'], draft.asOf.toIso8601String());
    expect(body.containsKey('radarEvidence'), isFalse);
  });
  test(
    'service rejects insecure origins and anonymous or disposed use',
    () async {
      for (final origin in [
        'http://example.invalid',
        'https://user:password@example.invalid',
        'https://example.invalid?token=x',
      ]) {
        expect(
          () => Rebound25ArtifactReviewService(baseUrl: origin),
          throwsArgumentError,
        );
      }
      var calls = 0;
      final service = Rebound25ArtifactReviewService(
        client: MockClient((request) async {
          calls++;
          return http.Response('{}', 200);
        }),
      );
      await expectLater(service.create(_draft()), throwsStateError);
      _owner(1);
      service.dispose();
      await expectLater(service.create(_draft()), throwsStateError);
      expect(calls, 0);
    },
  );
  test(
    'retry uses identical frozen body and concurrent calls deduplicate',
    () async {
      _owner(1);
      final responses = Completer<http.Response>();
      final bodies = <String>[];
      final service = Rebound25ArtifactReviewService(
        client: MockClient((request) async {
          expect(request.followRedirects, isFalse);
          expect(request.headers['Authorization'], 'Bearer synthetic-1');
          bodies.add(request.body);
          return responses.future;
        }),
      );
      final draft = _draft();
      final first = service.create(draft), duplicate = service.create(draft);
      expect(identical(first, duplicate), isTrue);
      final expectation = expectLater(first, throwsStateError);
      responses.complete(http.Response('{}', 503));
      await expectation;
      await expectLater(service.create(draft), throwsStateError);
      expect(bodies, [draft.encodedBody, draft.encodedBody]);
    },
  );
  test('session swap during response rejects without private read', () async {
    _owner(1);
    var calls = 0;
    final service = Rebound25ArtifactReviewService(
      client: MockClient((request) async {
        calls++;
        _owner(2);
        return http.Response('{}', 200);
      }),
    );
    await expectLater(service.create(_draft()), throwsStateError);
    expect(calls, 1);
  });
  test('oversized response rejected without interpreting JSON', () async {
    _owner(1);
    final service = Rebound25ArtifactReviewService(
      client: MockClient(
        (request) async => http.Response(
          'x' * (PrivateResearchHistoryService.maxResponseBytes + 1),
          200,
        ),
      ),
    );
    await expectLater(service.create(_draft()), throwsFormatException);
  });
  testWidgets(
    'human confirmation required, failed retry preserves identical draft and successful result is read only',
    (tester) async {
      _owner(1);
      final service = _Review()..fail = true;
      await tester.pumpWidget(
        _surface(
          Rebound25ArtifactReviewForm(artifact: _artifact(), service: service),
        ),
      );
      expect(service.drafts, isEmpty);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const Key('rebound25-review-submit')),
            )
            .onPressed,
        isNull,
      );
      await _fill(tester);
      await _tap(tester, 'rebound25-review-submit');
      await tester.pump();
      expect(find.byKey(const Key('rebound25-review-error')), findsOneWidget);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('rebound25-review-thesis')))
            .enabled,
        isFalse,
      );
      await _tap(tester, 'rebound25-review-submit');
      await tester.pump();
      expect(service.drafts.length, 2);
      expect(identical(service.drafts[0], service.drafts[1]), isTrue);
      expect(find.byKey(const Key('rebound25-review-result')), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const Key('rebound25-review-submit')),
            )
            .onPressed,
        isNull,
      );
    },
  );
  testWidgets('owner switch clears human text and suppresses late result', (
    tester,
  ) async {
    _owner(1);
    final pending = Completer<PrivateResearchCycleDetail>();
    final service = _Review()..pending = pending.future;
    await tester.pumpWidget(
      _surface(
        Rebound25ArtifactReviewForm(artifact: _artifact(), service: service),
      ),
    );
    await _fill(tester);
    await _tap(tester, 'rebound25-review-submit');
    expect(service.drafts.length, 1);
    _owner(2);
    await tester.pump();
    pending.complete(
      PrivateResearchCycleDetail(
        symbol: 'SYNTH',
        cycleHash: 'a' * 64,
        asOf: DateTime.now().toUtc(),
      ),
    );
    await tester.pump();
    expect(find.byKey(const Key('rebound25-review-result')), findsNothing);
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('rebound25-review-thesis')))
          .controller!
          .text,
      isEmpty,
    );
  });
}
