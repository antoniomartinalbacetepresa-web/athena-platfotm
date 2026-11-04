import 'package:app/features/analysis/services/athena_readiness_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('readiness service parses the operational contract', () async {
    final client = MockClient((request) async {
      expect(request.url.toString(), 'http://athena.test/api/v1/readiness');
      return http.Response(
        '''{
          "status":"athena_readiness_diagnostics",
          "asOf":"2026-09-10T09:00:00+00:00",
          "operationalReadiness":{
            "completionPercent":60.0,
            "passedGateCount":3,
            "totalGateCount":5,
            "ready":false,
            "blockers":["canonical_market_weighting_not_ready"]
          }
        }''',
        200,
      );
    });
    final service = AthenaReadinessService(
      baseUrl: 'http://athena.test',
      client: client,
    );

    final report = await service.getReport();

    expect(report.operationalReadiness.completionPercent, 60.0);
    expect(report.operationalReadiness.passedGateCount, 3);
    expect(report.operationalReadiness.totalGateCount, 5);
    expect(report.operationalReadiness.ready, isFalse);
    expect(
      report.operationalReadiness.blockers,
      contains('canonical_market_weighting_not_ready'),
    );
  });

  test('readiness service rejects non-success responses', () async {
    final service = AthenaReadinessService(
      baseUrl: 'http://athena.test',
      client: MockClient((_) async => http.Response('unavailable', 503)),
    );

    expect(service.getReport(), throwsException);
  });
}
