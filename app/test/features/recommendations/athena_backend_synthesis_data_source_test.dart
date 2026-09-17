import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:athena_tyche/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';

const hashA = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const hashB = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const hashC = 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';

String responseBody({bool recommendationInfluence = false, String fingerprint = hashA}) => '''
{"data":{"artifactBindingVerified":true,"synthesis":{"summary":"Escenario explicado","rationale":"Evidencia conjunta","uncertainties":["No es una predicción cierta"],"evidenceIds":["news:1","investors:1"],"inputFingerprint":"$fingerprint","recommendationInfluence":$recommendationInfluence,"automaticTrading":false},"provenance":{"inputFingerprint":"$hashA","news":{"artifactHash":"$hashB","assessmentBindings":[{"evidenceId":"news:1","assessmentFingerprint":"$hashC","sourceRef":"https://example.com/news/1"}],"userFacingTraceability":true,"recommendationInfluence":false,"automaticTrading":false},"investors":{"artifactHash":"$hashC","assessmentBindings":[{"evidenceId":"investors:1","assessmentFingerprint":"$hashB","sourceRef":"https://example.com/investors/1"}],"userFacingTraceability":true,"recommendationInfluence":false,"automaticTrading":false}}}}
''';

void main() {
  test('maps verified user-facing ATHENA provenance without trading authority', () async {
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async => http.Response(responseBody(), 200)),
    );

    final result = await source.getForResearchCycle(hashB);

    expect(result.summary, 'Escenario explicado');
    expect(result.provenance.inputFingerprint, hashA);
    expect(result.provenance.hasNews, isTrue);
    expect(result.provenance.hasInvestors, isTrue);
    expect(result.isSafe, isTrue);
    expect(result.recommendationInfluence, isFalse);
    expect(result.automaticTrading, isFalse);
  });

  test('loads latest canonical synthesis without inventing a cycle hash', () async {
    Uri? requested;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async {
        requested = request.url;
        return http.Response(responseBody(), 200);
      }),
    );

    final result = await source.getLatest();

    expect(requested.toString(), 'https://athena.example/api/v1/recommendations/professional-research/athena-synthesis/latest');
    expect(result.summary, 'Escenario explicado');
    expect(result.isSafe, isTrue);
  });

  test('latest synthesis fails closed on backend error', () async {
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async => http.Response('{"detail":"stale"}', 404)),
    );

    expect(() => source.getLatest(), throwsException);
  });

  test('fails closed when synthesis fingerprint diverges from provenance', () async {
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async => http.Response(responseBody(fingerprint: hashB), 200)),
    );

    expect(
      () => source.getForResearchCycle(hashB),
      throwsA(isA<FormatException>()),
    );
  });

  test('fails closed if backend grants recommendation influence', () async {
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.example',
      client: MockClient((request) async => http.Response(responseBody(recommendationInfluence: true), 200)),
    );

    expect(
      () => source.getForResearchCycle(hashB),
      throwsA(isA<FormatException>()),
    );
  });
}
