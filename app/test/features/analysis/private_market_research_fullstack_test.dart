// Mandatory in the dedicated ephemeral full-stack CI step. No external service.
import 'dart:convert';
import 'package:app/features/analysis/presentation/widgets/rebound25_research_panel.dart';
import 'package:app/features/analysis/services/rebound25_research_service.dart';

import 'package:app/features/analysis/presentation/widgets/persisted_market_research_form.dart';
import 'package:app/features/analysis/presentation/widgets/private_research_history_panel.dart';
import 'package:app/features/analysis/services/persisted_market_research_service.dart';
import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/market/data/providers/athena_backend_market_data_provider.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

const _base = String.fromEnvironment('ATHENA_SYNTHETIC_E2E_URL');

class _Creator extends PersistedMarketResearchService {
  _Creator(http.Client client) : super(baseUrl: _base, client: client);
  PersistedMarketResearchDraft? draft;
  @override
  Future<PrivateResearchCycleDetail> create(
    PersistedMarketResearchDraft value,
  ) {
    draft = value;
    return super.create(value);
  }
}

Future<void> _until(WidgetTester tester, Finder finder) async {
  for (var attempt = 0; attempt < 200 && finder.evaluate().isEmpty; attempt++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 50)),
    );
    await tester.pump();
  }
  expect(finder, findsOneWidget);
}

void main() {
  testWidgets(
    'real FastAPI creation, idempotent retry, owner isolation and later UI recovery',
    (tester) async {
      final uri = Uri.parse(_base);
      expect(uri.scheme, 'http');
      expect(['127.0.0.1', 'localhost'], contains(uri.host));
      expect(uri.userInfo, isEmpty);
      final client = http.Client();
      addTearDown(client.close);
      addTearDown(() {
        AuthSession.instance.clear();
      });
      final suffix = DateTime.now().microsecondsSinceEpoch;
      Future<(AuthAccount, String)> register(String label) async {
        final email = 'synthetic-$label-$suffix@example.invalid';
        const password = 'Synthetic-CI-Only-Password-2026!';
        final response = await client.post(
          Uri.parse('$_base/api/v1/auth/register'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'email': email, 'password': password}),
        );
        expect(response.statusCode, 201);
        final account = AuthAccount.fromMap(
          (jsonDecode(response.body) as Map<String, dynamic>)['account']
              as Map<String, dynamic>,
        );
        final token = await client.post(
          Uri.parse('$_base/api/v1/auth/token'),
          body: {'username': email, 'password': password},
        );
        expect(token.statusCode, 200);
        return (
          account,
          (jsonDecode(token.body) as Map<String, dynamic>)['access_token']
              as String,
        );
      }

      final first = (await tester.runAsync(() => register('a')))!;
      final second = (await tester.runAsync(() => register('b')))!;
      AuthSession.instance.establish(accessToken: first.$2, account: first.$1);
      final cutoff = DateTime.now().toUtc();
      final provider = AthenaBackendMarketDataProvider(baseUrl: _base);
      addTearDown(provider.dispose);
      final history = (await tester.runAsync(
        () => provider.getPersistedHistoricalData(
          instrumentId: 1,
          symbol: 'SYNTH',
          sourceProvider: 'synthetic_fixture',
          observedFrom: cutoff.subtract(const Duration(days: 365)),
          observedTo: cutoff,
          asOf: cutoff,
        ),
      ))!;
      expect(history.containsSyntheticEvidence, true);
      expect(history.points, isNotEmpty);
      final creator = _Creator(client);
      final reader = PrivateResearchHistoryService(
        baseUrl: _base,
        client: client,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: PersistedMarketResearchForm(
                quote: MarketQuote(
                  symbol: 'SYNTH',
                  instrumentId: 1,
                  companyName: 'Synthetic CI fixture',
                  canonicalIdentityStatus: 'matched_internal_listing',
                  currentPrice: 101,
                  change: 0,
                  changePercentage: 0,
                  currency: 'USD',
                  sourceProvider: 'synthetic_fixture',
                  updatedAt: cutoff,
                ),
                history: history,
                service: creator,
                historyService: reader,
              ),
            ),
          ),
        ),
      );
      await tester.enterText(
        find.byKey(const Key('market-cycle-thesis')),
        'Synthetic full-stack research question',
      );
      await tester.enterText(
        find.byKey(const Key('market-cycle-objection')),
        'Fixtures do not establish market performance',
      );
      await tester.ensureVisible(find.byKey(const Key('market-cycle-review')));
      await tester.tap(find.byKey(const Key('market-cycle-review')));
      await tester.pump();
      await tester.ensureVisible(find.byKey(const Key('market-cycle-submit')));
      await tester.tap(find.byKey(const Key('market-cycle-submit')));
      await tester.pump();
      await _until(tester, find.byKey(const Key('market-cycle-result')));
      final recovered = (await tester.runAsync(
        () => creator.create(creator.draft!),
      ))!;
      final index = (await tester.runAsync(
        () => reader.load(symbol: 'SYNTH'),
      ))!;
      expect(index.items.length, 1);
      expect(index.items.single.cycleHash, recovered.cycleHash);
      final denial = (await tester.runAsync(
        () => client.get(
          Uri.parse(
            '$_base/api/v1/recommendations/'
            'professional-research/research-cycle/private/${recovered.cycleHash}',
          ),
          headers: {'Authorization': 'Bearer ${second.$2}'},
        ),
      ))!;
      expect(denial.statusCode, 404);
      AuthSession.instance.establish(
        accessToken: second.$2,
        account: second.$1,
      );
      await tester.pump();
      expect(find.byKey(const Key('market-cycle-result')), findsNothing);
      expect(
        (await tester.runAsync(() => reader.load(symbol: 'SYNTH')))!.items,
        isEmpty,
      );
      AuthSession.instance.establish(accessToken: first.$2, account: first.$1);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: PrivateResearchHistoryPanel(
                symbol: 'SYNTH',
                service: reader,
              ),
            ),
          ),
        ),
      );
      await _until(tester, find.byKey(const Key('private-research-heading')));
      await tester.ensureVisible(find.text('Abrir investigación'));
      await tester.tap(find.text('Abrir investigación'));
      await tester.pump();
      await _until(tester, find.byKey(const Key('private-research-detail')));
      for (final kind in ['News', 'ATHENA', 'Investors']) {
        await _until(
          tester,
          find.textContaining('Síntesis $kind no disponible:'),
        );
      }
      final strategyService = Rebound25ResearchService(baseUrl: _base, client: client);
      await tester.pumpWidget(MaterialApp(home: Scaffold(body: SingleChildScrollView(
        child: Rebound25ResearchPanel(service: strategyService)))));
      expect(find.byKey(const Key('rebound25-synthetic-warning')), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('rebound25-run')));
      await tester.tap(find.byKey(const Key('rebound25-run'))); await tester.pump();
      await _until(tester, find.byKey(const Key('rebound25-result')));
      expect(find.textContaining('liquidación hipotética'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      strategyService.dispose();
      creator.dispose();
      reader.dispose();
    },
    skip: _base.isEmpty,
  );
}
