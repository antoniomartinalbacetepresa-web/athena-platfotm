import 'dart:convert';

import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/analysis/presentation/widgets/private_research_history_panel.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:flutter/material.dart';
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

void _signIn(AuthSession session) {
  final now = DateTime.now().toUtc();
  session.establish(
    accessToken: 'fixture-token',
    account: AuthAccount(
      id: 1,
      email: 'fixture@example.invalid',
      isActive: true,
      createdAt: now,
      updatedAt: now,
    ),
  );
}

Map<String, dynamic> _reference(DateTime cutoff, String category) => {
  'evidenceId': category,
  'category': category,
  'summary': 'Synthetic $category document',
  'source': 'synthetic_source',
  'sourceRef': 'https://source.invalid/$category',
  'publishedAt': cutoff.subtract(const Duration(days: 2)).toIso8601String(),
  'availableAt': cutoff.subtract(const Duration(days: 1)).toIso8601String(),
};

class _History extends PrivateResearchHistoryService {
  _History(this.entry, this.detail, {this.investors});
  final PrivateResearchEntry entry;
  final PrivateResearchCycleDetail detail;
  final PrivateResearchSynthesis? investors;
  @override
  Future<PrivateResearchPage> load({
    required String symbol,
    int limit = 20,
  }) async => PrivateResearchPage([entry]);
  @override
  Future<PrivateResearchCycleDetail> loadCycle(
    PrivateResearchEntry entry,
  ) async => detail;
  @override
  Future<PrivateResearchSynthesis?> loadInvestorsSynthesis(
    PrivateResearchEntry entry,
  ) async => investors;
  @override
  Future<PrivateResearchSynthesis?> loadSynthesis(
    PrivateResearchEntry entry, {
    required bool athena,
  }) async => null;
}

void main() {
  for (final defect in [
    'none',
    'future-available',
    'future-publication',
    'duplicate',
    'invalid-date',
  ]) {
    test(
      'canonical document references enforce temporal identity: $defect',
      () async {
        final session = AuthSession.forTesting(_Store());
        _signIn(session);
        final cutoff = DateTime.now().toUtc().subtract(
          const Duration(minutes: 1),
        );
        final refs = [
          _reference(cutoff, 'news'),
          _reference(cutoff, 'investors'),
        ];
        if (defect == 'future-available') {
          refs[0]['availableAt'] = cutoff
              .add(const Duration(seconds: 1))
              .toIso8601String();
        }
        if (defect == 'future-publication') {
          refs[0]['publishedAt'] = cutoff.toIso8601String();
        }
        if (defect == 'duplicate') {
          refs[1]['evidenceId'] = 'news';
        }
        if (defect == 'invalid-date') {
          refs[0]['publishedAt'] = 'invalid';
        }
        final client = MockClient(
          (_) async => http.Response(
            jsonEncode({
              'data': {
                'advisoryStatus': 'no_advice',
                'productionEligible': false,
                'automaticTrading': false,
                'isWeightingReady': false,
                'persistence': {'cycleHash': 'a' * 64},
                'package': {
                  'cycle': {
                    'symbol': 'SYNTH',
                    'asOf': cutoff.toIso8601String(),
                    'integrity': {'algorithm': 'sha256', 'cycleHash': 'a' * 64},
                  },
                  'radar': {
                    'candidates': [
                      {'evidence': refs},
                    ],
                  },
                },
              },
            }),
            200,
          ),
        );
        final service = PrivateResearchHistoryService(
          client: client,
          session: session,
        );
        final result = service.loadCycle(
          PrivateResearchEntry(
            cycleHash: 'a' * 64,
            symbol: 'SYNTH',
            asOf: cutoff,
          ),
        );
        if (defect == 'none') {
          final detail = await result;
          expect(detail.evidence.map((e) => e.category), ['news', 'investors']);
          expect(
            detail.evidence.first.publishedAt!.isBefore(
              detail.evidence.first.availableAt,
            ),
            true,
          );
          expect(() => detail.evidence.clear(), throwsUnsupportedError);
        } else {
          await expectLater(result, throwsFormatException);
        }
        client.close();
      },
    );
  }
  testWidgets(
    'private review displays publication, availability and source without fetching it',
    (tester) async {
      _signIn(AuthSession.instance);
      final cutoff = DateTime.now().toUtc().subtract(const Duration(days: 1));
      final entry = PrivateResearchEntry(
        cycleHash: 'a' * 64,
        symbol: 'SYNTH',
        asOf: cutoff,
      );
      final detail = PrivateResearchCycleDetail(
        symbol: 'SYNTH',
        cycleHash: entry.cycleHash,
        asOf: cutoff,
        evidence: [
          PrivateResearchEvidence(
            id: 'filing',
            category: 'investors',
            summary: 'Synthetic filing',
            source: 'synthetic_source',
            sourceRef: 'https://source.invalid/filing',
            availableAt: cutoff,
            publishedAt: cutoff.subtract(const Duration(days: 10)),
          ),
        ],
      );
      final service = _History(
        entry,
        detail,
        investors: PrivateResearchSynthesis(
          kind: 'Investors',
          summary: 'Synthetic Investors interpretation, not source truth',
          cycleHash: entry.cycleHash,
          asOf: cutoff,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: PrivateResearchHistoryPanel(
                symbol: 'SYNTH',
                service: service,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abrir investigación'));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('private-evidence-filing')),
        findsOneWidget,
      );
      expect(
        find.textContaining('https://source.invalid/filing'),
        findsOneWidget,
      );
      expect(find.textContaining('Publicación:'), findsOneWidget);
      expect(find.textContaining('posiciones históricas'), findsOneWidget);
      expect(
        find.text('Síntesis Investors persistida (solo lectura)'),
        findsOneWidget,
      );
      expect(
        find.text('Synthetic Investors interpretation, not source truth'),
        findsOneWidget,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      AuthSession.instance.clear();
      service.dispose();
    },
  );
}
