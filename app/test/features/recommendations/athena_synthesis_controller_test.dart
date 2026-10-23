import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/features/recommendations/controllers/athena_synthesis_controller.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_synthesis_data_source.dart';

const cycleHash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const inputFingerprint = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
const newsHash = 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';
const assessmentFingerprint = 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';

Map<String, dynamic> validPayload() => {
      'data': {
        'artifactBindingVerified': true,
        'presentationOnly': true,
        'recommendationInfluence': false,
        'automaticTrading': false,
        'synthesis': {
          'inputFingerprint': inputFingerprint,
          'summary': 'ATHENA integra la evidencia verificada.',
          'rationale': 'La explicación conserva trazabilidad hasta News.',
          'uncertainties': ['La evidencia futura puede cambiar el escenario.'],
          'evidenceIds': ['news:1'],
          'recommendationInfluence': false,
          'automaticTrading': false,
        },
        'provenance': {
          'inputFingerprint': inputFingerprint,
          'news': {
            'artifactHash': newsHash,
            'userFacingTraceability': true,
            'recommendationInfluence': false,
            'automaticTrading': false,
            'assessmentBindings': [
              {'evidenceId': 'news:1', 'assessmentFingerprint': assessmentFingerprint, 'sourceRef': 'https://example.com/news/1'}
            ],
          },
        },
      },
    };

void main() {
  test('controller exposes verified ATHENA synthesis and provenance state', () async {
    final source = AthenaBackendSynthesisDataSource(baseUrl: 'https://athena.test', client: MockClient((request) async => http.Response(jsonEncode(validPayload()), 200)));
    final controller = AthenaSynthesisController(dataSource: source);
    await controller.load(cycleHash);
    expect(controller.isLoading, isFalse);
    expect(controller.error, isNull);
    expect(controller.hasData, isTrue);
    expect(controller.synthesis!.summary, contains('evidencia verificada'));
    expect(controller.synthesis!.provenance.hasNews, isTrue);
    expect(controller.synthesis!.provenance.hasInvestors, isFalse);
    expect(controller.synthesis!.isSafe, isTrue);
  });

  test('controller fails closed and clears stale synthesis after provenance failure', () async {
    var valid = true;
    final source = AthenaBackendSynthesisDataSource(baseUrl: 'https://athena.test', client: MockClient((request) async {
      final payload = validPayload();
      if (!valid) (payload['data']['provenance'] as Map<String, dynamic>)['inputFingerprint'] = 'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';
      return http.Response(jsonEncode(payload), 200);
    }));
    final controller = AthenaSynthesisController(dataSource: source);
    await controller.load(cycleHash);
    expect(controller.hasData, isTrue);
    valid = false;
    await controller.load(cycleHash);
    expect(controller.hasData, isFalse);
    expect(controller.error, contains('No se pudo verificar'));
    expect(controller.isLoading, isFalse);
  });

  test('controller clears stale synthesis immediately while a reload is pending', () async {
    final pending = Completer<http.Response>();
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.test',
      client: MockClient((request) async {
        requests += 1;
        if (requests == 1) {
          return http.Response(jsonEncode(validPayload()), 200);
        }
        return pending.future;
      }),
    );
    final controller = AthenaSynthesisController(dataSource: source);

    await controller.load(cycleHash);
    expect(controller.hasData, isTrue);

    final reload = controller.loadLatest();
    expect(controller.isLoading, isTrue);
    expect(controller.hasData, isFalse);
    expect(controller.synthesis, isNull);

    pending.complete(http.Response(jsonEncode(validPayload()), 200));
    await reload;
    expect(controller.isLoading, isFalse);
    expect(controller.hasData, isTrue);
  });

  test('retry reloads the same research cycle after a transient backend failure', () async {
    var attempts = 0;
    final source = AthenaBackendSynthesisDataSource(baseUrl: 'https://athena.test', client: MockClient((request) async {
      attempts += 1;
      if (attempts == 1) return http.Response('unavailable', 503);
      return http.Response(jsonEncode(validPayload()), 200);
    }));
    final controller = AthenaSynthesisController(dataSource: source);
    await controller.load(cycleHash);
    expect(controller.error, isNotNull);
    expect(controller.hasData, isFalse);
    await controller.retry();
    expect(attempts, 2);
    expect(controller.error, isNull);
    expect(controller.hasData, isTrue);
    expect(controller.cycleHash, cycleHash);
  });

  test('clear invalidates an older latest response after a new latest request', () async {
    final older = Completer<http.Response>();
    final newer = Completer<http.Response>();
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.test',
      client: MockClient((_) {
        requests += 1;
        return requests == 1 ? older.future : newer.future;
      }),
    );
    final controller = AthenaSynthesisController(dataSource: source);

    final staleRequest = controller.loadLatest();
    controller.clear();
    final currentRequest = controller.loadLatest();

    older.complete(http.Response(jsonEncode(validPayload()), 200));
    await staleRequest;
    expect(controller.isLoading, isTrue);
    expect(controller.hasData, isFalse);

    final currentPayload = validPayload();
    ((currentPayload['data'] as Map<String, dynamic>)['synthesis']
        as Map<String, dynamic>)['summary'] = 'Síntesis actual';
    newer.complete(http.Response(jsonEncode(currentPayload), 200));
    await currentRequest;
    expect(controller.isLoading, isFalse);
    expect(controller.synthesis!.summary, 'Síntesis actual');
    controller.dispose();
  });

  test('clear invalidates an older response for the same research cycle', () async {
    final older = Completer<http.Response>();
    final newer = Completer<http.Response>();
    var requests = 0;
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.test',
      client: MockClient((_) {
        requests += 1;
        return requests == 1 ? older.future : newer.future;
      }),
    );
    final controller = AthenaSynthesisController(dataSource: source);

    final staleRequest = controller.load(cycleHash);
    controller.clear();
    final currentRequest = controller.load(cycleHash);

    older.complete(http.Response(jsonEncode(validPayload()), 200));
    await staleRequest;
    expect(controller.hasData, isFalse);
    expect(controller.isLoading, isTrue);

    newer.complete(http.Response(jsonEncode(validPayload()), 200));
    await currentRequest;
    expect(controller.hasData, isTrue);
    expect(controller.isLoading, isFalse);
    controller.dispose();
  });

  test('disposing a controller prevents pending synthesis from being published', () async {
    final pending = Completer<http.Response>();
    final source = AthenaBackendSynthesisDataSource(
      baseUrl: 'https://athena.test',
      client: MockClient((_) => pending.future),
    );
    final controller = AthenaSynthesisController(dataSource: source);

    final request = controller.loadLatest();
    expect(controller.isLoading, isTrue);
    controller.dispose();
    pending.complete(http.Response(jsonEncode(validPayload()), 200));
    await request;

    expect(controller.hasData, isFalse);
    expect(controller.isLoading, isFalse);
    // Disposed controllers must ignore subsequent refresh attempts.
    await controller.loadLatest();
    expect(controller.hasData, isFalse);
  });
}
