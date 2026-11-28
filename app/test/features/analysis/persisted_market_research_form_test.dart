import 'dart:async';

import 'package:app/features/analysis/presentation/widgets/persisted_market_research_form.dart';
import 'package:app/features/analysis/services/persisted_market_research_service.dart';
import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/market/data/models/market_data_point.dart';
import 'package:app/features/market/data/models/persisted_market_history.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _Creator extends PersistedMarketResearchService {
  final drafts = <PersistedMarketResearchDraft>[];
  Future<PrivateResearchCycleDetail> Function(PersistedMarketResearchDraft)?
  respond;
  @override
  Future<PrivateResearchCycleDetail> create(
    PersistedMarketResearchDraft draft,
  ) {
    drafts.add(draft);
    return respond!(draft);
  }
}

class _History extends PrivateResearchHistoryService {
  _History({this.items = const []});
  final List<PrivateResearchEntry> items;
  @override
  Future<PrivateResearchPage> load({
    required String symbol,
    int limit = 20,
  }) async => PrivateResearchPage(items);
}

class _FailHistory extends PrivateResearchHistoryService {
  int calls = 0;
  @override
  Future<PrivateResearchPage> load({
    required String symbol,
    int limit = 20,
  }) async {
    calls++;
    if (calls == 1) {
      throw StateError('Synthetic read failure');
    }
    return const PrivateResearchPage([]);
  }
}

void owner(int id) {
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

Widget _surface(
  _Creator service, {
  bool synthetic = true,
  PrivateResearchHistoryService? historyService,
}) {
  final cutoff = DateTime.now().toUtc().subtract(const Duration(minutes: 1));
  return MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(
        child: PersistedMarketResearchForm(
          quote: MarketQuote(
            symbol: 'SYNTH',
            instrumentId: 7,
            companyName: 'Synthetic fixture',
            canonicalIdentityStatus: 'matched_internal_listing',
            currentPrice: 100,
            change: 0,
            changePercentage: 0,
            currency: 'USD',
            sourceProvider: 'synthetic_fixture',
            updatedAt: cutoff,
          ),
          history: PersistedMarketHistory(
            asOf: cutoff,
            truncated: false,
            evidenceKind: synthetic
                ? PersistedMarketEvidenceKind.syntheticFixture
                : PersistedMarketEvidenceKind.unverified,
            points: [
              MarketDataPoint(
                symbol: 'SYNTH',
                timestamp: cutoff,
                close: 100,
                currency: 'USD',
                providerId: 'fixture',
              ),
            ],
          ),
          service: service,
          historyService: historyService ?? _History(),
        ),
      ),
    ),
  );
}

Future<void> prepare(WidgetTester tester) async {
  await tester.enterText(
    find.byKey(const Key('market-cycle-thesis')),
    'Research question',
  );
  await tester.enterText(
    find.byKey(const Key('market-cycle-objection')),
    'Synthetic observations do not establish profitability',
  );
  await tester.ensureVisible(find.byKey(const Key('market-cycle-review')));
  await tester.tap(find.byKey(const Key('market-cycle-review')));
  await tester.pump();
  await tester.ensureVisible(find.byKey(const Key('market-cycle-submit')));
}

void main() {
  testWidgets(
    'confirmed rejection allows deliberate correction with fresh human review',
    (tester) async {
      owner(1);
      final creator = _Creator();
      creator.respond = (_) async =>
          throw const PersistedMarketResearchRejected(400);
      await tester.pumpWidget(_surface(creator));
      await prepare(tester);
      await tester.tap(find.byKey(const Key('market-cycle-submit')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('market-cycle-rejected')), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const Key('market-cycle-correct-draft')),
      );
      await tester.tap(find.byKey(const Key('market-cycle-correct-draft')));
      await tester.pump();
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('market-cycle-thesis')))
            .controller!
            .text,
        'Research question',
      );
      expect(
        tester
            .widget<CheckboxListTile>(
              find.byKey(const Key('market-cycle-review')),
            )
            .value,
        false,
      );
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('market-cycle-sources')))
            .enabled,
        true,
      );
      expect(creator.drafts.length, 1);
      creator.dispose();
    },
  );
  testWidgets(
    'source history failure is explicit and retry recovers without creating a cycle',
    (tester) async {
      owner(1);
      final creator = _Creator();
      final history = _FailHistory();
      await tester.pumpWidget(_surface(creator, historyService: history));
      final load = find.byKey(const Key('market-cycle-load-sources'));
      await tester.ensureVisible(load);
      await tester.tap(load);
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('market-cycle-sources-error')),
        findsOneWidget,
      );
      await tester.tap(load);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('market-cycle-sources-error')), findsNothing);
      expect(
        find.text('No hay ciclos privados para este símbolo.'),
        findsOneWidget,
      );
      expect(history.calls, 2);
      expect(creator.drafts, isEmpty);
      creator.dispose();
      history.dispose();
    },
  );
  testWidgets(
    'source candidates are owner-private and selectable without pasting a hash',
    (tester) async {
      owner(1);
      final creator = _Creator();
      final history = _History(
        items: [
          PrivateResearchEntry(
            cycleHash: 'c' * 64,
            symbol: 'SYNTH',
            asOf: DateTime.now().toUtc().subtract(const Duration(days: 1)),
          ),
        ],
      );
      await tester.pumpWidget(_surface(creator, historyService: history));
      await tester.ensureVisible(
        find.byKey(const Key('market-cycle-load-sources')),
      );
      await tester.tap(find.byKey(const Key('market-cycle-load-sources')));
      await tester.pumpAndSettle();
      final option = find.byKey(
        ValueKey('market-cycle-use-source-${'c' * 64}'),
      );
      await tester.ensureVisible(option);
      await tester.tap(option);
      await tester.pump();
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('market-cycle-sources')))
            .controller!
            .text,
        'c' * 64,
      );
      expect(creator.drafts, isEmpty);
      owner(2);
      await tester.pump();
      expect(option, findsNothing);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('market-cycle-sources')))
            .controller!
            .text,
        isEmpty,
      );
      creator.dispose();
      history.dispose();
    },
  );
  testWidgets('invalid source hash fails before submission', (tester) async {
    owner(1);
    final creator = _Creator();
    await tester.pumpWidget(_surface(creator));
    await tester.enterText(
      find.byKey(const Key('market-cycle-sources')),
      'invalid',
    );
    await prepare(tester);
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pump();
    expect(find.byKey(const Key('market-cycle-validation')), findsOneWidget);
    expect(creator.drafts, isEmpty);
    creator.dispose();
  });
  testWidgets('explicit private source selection is frozen in the request', (
    tester,
  ) async {
    owner(1);
    final creator = _Creator();
    creator.respond = (_) async => throw StateError('Synthetic unavailable');
    await tester.pumpWidget(_surface(creator));
    await tester.enterText(
      find.byKey(const Key('market-cycle-sources')),
      'c' * 64,
    );
    await prepare(tester);
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pumpAndSettle();
    expect(creator.drafts.single.sourceCycleHashes, ['c' * 64]);
    creator.dispose();
  });

  setUp(() {
    AuthSession.instance.clear();
  });
  tearDown(() {
    AuthSession.instance.clear();
  });

  testWidgets('guest cannot submit private research', (tester) async {
    final creator = _Creator();
    await tester.pumpWidget(_surface(creator));
    expect(find.byKey(const Key('market-cycle-auth-required')), findsOneWidget);
    expect(find.byKey(const Key('market-cycle-submit')), findsNothing);
    expect(creator.drafts, isEmpty);
    creator.dispose();
  });
  testWidgets('unverified history never offers creation', (tester) async {
    owner(1);
    final creator = _Creator();
    await tester.pumpWidget(_surface(creator, synthetic: false));
    expect(find.byKey(const Key('market-cycle-submit')), findsNothing);
    expect(creator.drafts, isEmpty);
    creator.dispose();
  });
  testWidgets('mandatory human context and review fail before transport', (
    tester,
  ) async {
    owner(1);
    final creator = _Creator();
    await tester.pumpWidget(_surface(creator));
    await tester.ensureVisible(find.byKey(const Key('market-cycle-submit')));
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pump();
    expect(find.byKey(const Key('market-cycle-validation')), findsOneWidget);
    expect(creator.drafts, isEmpty);
    creator.dispose();
  });
  testWidgets(
    'explicit creation blocks double tap and exposes private result',
    (tester) async {
      owner(1);
      final creator = _Creator();
      final pending = Completer<PrivateResearchCycleDetail>();
      creator.respond = (_) => pending.future;
      await tester.pumpWidget(_surface(creator));
      await prepare(tester);
      await tester.tap(find.byKey(const Key('market-cycle-submit')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('market-cycle-submit')));
      await tester.pump();
      expect(creator.drafts.length, 1);
      expect(find.byKey(const Key('market-cycle-loading')), findsOneWidget);
      final request = creator.drafts.single;
      expect(
        request.asOf.isAfter(
          DateTime.now().toUtc().subtract(const Duration(seconds: 10)),
        ),
        true,
      );
      pending.complete(
        PrivateResearchCycleDetail(
          symbol: 'SYNTH',
          cycleHash: 'a' * 64,
          asOf: request.asOf,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('market-cycle-result')), findsOneWidget);
      expect(find.byKey(const Key('private-research-empty')), findsOneWidget);
      creator.dispose();
    },
  );
  testWidgets('uncertain write retries the identical frozen draft', (
    tester,
  ) async {
    owner(1);
    final creator = _Creator();
    creator.respond = (_) async => throw StateError('synthetic interruption');
    await tester.pumpWidget(_surface(creator));
    await prepare(tester);
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-cycle-error')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('market-cycle-submit')));
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pumpAndSettle();
    expect(creator.drafts.length, 2);
    expect(identical(creator.drafts[0], creator.drafts[1]), true);
    creator.dispose();
  });
  testWidgets('owner change clears private input and hides late result', (
    tester,
  ) async {
    owner(1);
    final creator = _Creator();
    final pending = Completer<PrivateResearchCycleDetail>();
    creator.respond = (_) => pending.future;
    await tester.pumpWidget(_surface(creator));
    await prepare(tester);
    await tester.tap(find.byKey(const Key('market-cycle-submit')));
    await tester.pump();
    final request = creator.drafts.single;
    owner(2);
    await tester.pump();
    pending.complete(
      PrivateResearchCycleDetail(
        symbol: 'SYNTH',
        cycleHash: 'a' * 64,
        asOf: request.asOf,
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('market-cycle-result')), findsNothing);
    expect(find.text('Research question'), findsNothing);
    creator.dispose();
  });
}
