import 'dart:convert';

import 'package:app/features/analysis/services/private_research_history_service.dart';
import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
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

void main() {
  for (final defect in [
    'none',
    'future-publication',
    'future-availability',
    'binding',
    'cycle',
    'model',
    'hash',
  ]) {
    test(
      'private Investors synthesis validates canonical assessment: $defect',
      () async {
        final cutoff = DateTime.now().toUtc().subtract(
          const Duration(minutes: 1),
        );
        final session = AuthSession.forTesting(_Store());
        session.establish(
          accessToken: 'fixture-token',
          account: AuthAccount(
            id: 1,
            email: 'fixture@example.invalid',
            isActive: true,
            createdAt: cutoff,
            updatedAt: cutoff,
          ),
        );
        final assessment = <String, dynamic>{
          'evidenceId': 'synthetic-filing',
          'symbol': 'SYNTH',
          'sourceRef': 'https://source.invalid/filing',
          'assessmentFingerprint': 'b' * 64,
          'summary': 'Synthetic historical filing assessment',
          'publishedAt':
              (defect == 'future-publication'
                      ? cutoff.add(const Duration(days: 1))
                      : cutoff.subtract(const Duration(days: 10)))
                  .toIso8601String(),
          'availableAt':
              (defect == 'future-availability'
                      ? cutoff.add(const Duration(days: 1))
                      : cutoff.subtract(const Duration(days: 1)))
                  .toIso8601String(),
          'generatedAt': cutoff.toIso8601String(),
        };
        var calls = 0;
        final client = MockClient((request) async {
          calls++;
          expect(request.headers['Authorization'], 'Bearer fixture-token');
          expect(
            request.url.path,
            endsWith('/research-cycle/private/${'a' * 64}/investors-synthesis'),
          );
          return http.Response(
            jsonEncode({
              'data': {
                'cycleHash': defect == 'cycle' ? 'c' * 64 : 'a' * 64,
                'cycleBindingVerified': true,
                'automaticTrading': false,
                'automaticScoring': false,
                'recommendationInfluence': false,
                'persistence': {
                  'cycleHash': 'a' * 64,
                  'synthesisHash': defect == 'hash' ? null : 'd' * 64,
                },
                'provenance': {
                  'artifactType': 'canonical_investors_synthesis',
                  'artifactHash': 'd' * 64,
                  'assessmentBindings': [
                    {
                      'evidenceId': assessment['evidenceId'],
                      'sourceRef': defect == 'binding'
                          ? 'https://other.invalid'
                          : assessment['sourceRef'],
                      'assessmentFingerprint': 'b' * 64,
                    },
                  ],
                },
                'synthesis': {
                  'asOf': cutoff.toIso8601String(),
                  'assessedCount': 1,
                  'assessments': [assessment],
                  'modelExecutionVerified': defect == 'model',
                  'productionTruthClaimed': false,
                  'automaticTrading': false,
                  'recommendationInfluence': false,
                },
              },
            }),
            200,
          );
        });
        final service = PrivateResearchHistoryService(
          client: client,
          session: session,
        );
        final future = service.loadInvestorsSynthesis(
          PrivateResearchEntry(
            cycleHash: 'a' * 64,
            symbol: 'SYNTH',
            asOf: cutoff,
          ),
        );
        if (defect == 'none') {
          final synthesis = await future;
          expect(synthesis!.kind, 'Investors');
          expect(synthesis.summary, contains('Publicación:'));
          expect(synthesis.summary, contains('https://source.invalid/filing'));
        } else {
          await expectLater(future, throwsFormatException);
        }
        expect(calls, 1);
        client.close();
      },
    );
  }
  for (final status in [401, 403, 404]) {
    test('private Investors HTTP $status never falls back', () async {
      final cutoff = DateTime.now().toUtc().subtract(
        const Duration(minutes: 1),
      );
      final session = AuthSession.forTesting(_Store());
      session.establish(
        accessToken: 'fixture-token',
        account: AuthAccount(
          id: 1,
          email: 'fixture@example.invalid',
          isActive: true,
          createdAt: cutoff,
          updatedAt: cutoff,
        ),
      );
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return http.Response('{}', status);
      });
      final service = PrivateResearchHistoryService(
        client: client,
        session: session,
      );
      final future = service.loadInvestorsSynthesis(
        PrivateResearchEntry(
          cycleHash: 'a' * 64,
          symbol: 'SYNTH',
          asOf: cutoff,
        ),
      );
      if (status == 404) {
        expect(await future, isNull);
      } else {
        await expectLater(future, throwsStateError);
      }
      expect(calls, 1);
      client.close();
    });
  }
}
