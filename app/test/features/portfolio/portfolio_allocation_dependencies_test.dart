import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/di/portfolio_allocation_dependencies.dart';

void main() {
  group('PortfolioAllocationDependencies', () {
    test('wires all allocation boundaries to the same explicit backend', () {
      final dependencies = PortfolioAllocationDependencies.create(
        baseUrl: 'https://athena.example.test/',
      );
      addTearDown(dependencies.dispose);

      expect(
        dependencies.authorityDataSource.baseUrl,
        'https://athena.example.test',
      );
      expect(
        dependencies.allocationDataSource.baseUrl,
        'https://athena.example.test',
      );
      expect(
        dependencies.policyDataSource.baseUrl,
        'https://athena.example.test',
      );
      expect(
        identical(
          dependencies.allocationController.authorityDataSource,
          dependencies.authorityDataSource,
        ),
        isTrue,
      );
      expect(
        identical(
          dependencies.allocationController.allocationDataSource,
          dependencies.allocationDataSource,
        ),
        isTrue,
      );
      expect(
        identical(
          dependencies.policyController.dataSource,
          dependencies.policyDataSource,
        ),
        isTrue,
      );
      expect(dependencies.policyController.selectedPolicy, isNull);
      expect(dependencies.allocationController.candidate, isNull);
    });

    test('fails closed when backend URL is blank', () {
      expect(
        () => PortfolioAllocationDependencies.create(baseUrl: '   '),
        throwsStateError,
      );
    });

    test('fails closed when backend URL is not HTTP(S)', () {
      expect(
        () => PortfolioAllocationDependencies.create(
          baseUrl: 'file:///tmp/athena',
        ),
        throwsStateError,
      );
    });
  });
}
