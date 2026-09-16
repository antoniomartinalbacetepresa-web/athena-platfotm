import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/recommendations/di/recommendation_dependencies.dart';

void main() {
  test('wires every recommendation backend reader to the same real backend', () {
    final dependencies = RecommendationDependencies.create(
      baseUrl: 'https://athena.example.test',
    );
    addTearDown(dependencies.dispose);

    expect(
      dependencies.learningDataSource.baseUrl,
      'https://athena.example.test',
    );
    expect(
      dependencies.shadowCandidateDataSource.baseUrl,
      'https://athena.example.test',
    );
    expect(
      dependencies.productionDataSource.baseUrl,
      'https://athena.example.test',
    );
    expect(
      dependencies.professionalDossierDataSource.baseUrl,
      'https://athena.example.test',
    );
  });

  test('fails closed when ATHENA_BACKEND_URL is explicitly empty', () {
    expect(
      () => RecommendationDependencies.create(baseUrl: '   '),
      throwsA(isA<StateError>()),
    );
  });
}
