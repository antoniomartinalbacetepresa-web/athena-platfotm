import 'package:app/features/portfolio/data/athena_backend_portfolio_allocation_policy_data_source.dart';
import 'package:app/features/portfolio/models/portfolio_allocation_policy.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_allocation_policy_controller.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakePolicyDataSource
    extends AthenaBackendPortfolioAllocationPolicyDataSource {
  final List<PortfolioAllocationPolicy> result;

  _FakePolicyDataSource(this.result) : super(baseUrl: 'http://localhost:8000');

  @override
  Future<List<PortfolioAllocationPolicy>> listPolicies() async => result;
}

PortfolioAllocationPolicy _policy({
  String id = 'balanced-usd-v1',
  String fingerprint =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
}) {
  return PortfolioAllocationPolicy(
    policyId: id,
    baseCurrency: 'USD',
    maximumInstrumentSleeveWeight: 0.20,
    minimumCashReserveWeight: 0.10,
    maximumAbsolutePairCorrelation: 0.80,
    minimumCorrelationSampleCount: 60,
    maximumCorrelationAgeSeconds: 86400,
    registeredAt: DateTime.parse('2026-09-06T12:00:00Z'),
    policyFingerprint: fingerprint,
  );
}

void main() {
  test('does not auto-select even when exactly one policy exists', () async {
    final controller = PortfolioAllocationPolicyController(
      dataSource: _FakePolicyDataSource([_policy()]),
    );

    await controller.load();

    expect(controller.policies, hasLength(1));
    expect(controller.selectedPolicy, isNull);
    expect(controller.requiresExplicitSelection, isTrue);
    expect(controller.hasNoPolicies, isFalse);
  });

  test('selects only an explicitly requested verified loaded policy', () async {
    final first = _policy();
    final second = _policy(
      id: 'conservative-usd-v1',
      fingerprint:
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    );
    final controller = PortfolioAllocationPolicyController(
      dataSource: _FakePolicyDataSource([first, second]),
    );
    await controller.load();

    controller.selectPolicy('conservative-usd-v1');

    expect(controller.selectedPolicy, same(second));
    expect(controller.requiresExplicitSelection, isFalse);
    expect(
      () => controller.selectPolicy('unknown-policy'),
      throwsA(isA<StateError>()),
    );
  });

  test('empty registry stays explicitly without a selected policy', () async {
    final controller = PortfolioAllocationPolicyController(
      dataSource: _FakePolicyDataSource(const []),
    );

    await controller.load();

    expect(controller.policies, isEmpty);
    expect(controller.selectedPolicy, isNull);
    expect(controller.requiresExplicitSelection, isFalse);
    expect(controller.hasNoPolicies, isTrue);
  });
}
