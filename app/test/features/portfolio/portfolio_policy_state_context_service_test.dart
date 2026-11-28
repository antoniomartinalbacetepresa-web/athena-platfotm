import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/athena_portfolio_policy_state.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/services/portfolio_policy_state_context_service.dart';

PortfolioPosition _verifiedPosition({
  AthenaPortfolioPolicyState? state = AthenaPortfolioPolicyState.fullLong,
}) {
  return PortfolioPosition(
    symbol: 'TEST',
    companyName: 'Test Corp',
    shares: 10,
    averagePrice: 100,
    currentPrice: 110,
    priceCurrency: 'USD',
    exchange: 'NMS',
    databaseInstrumentId: 42,
    canonicalInstrumentId: 'instrument:42',
    canonicalIssuerId: 'issuer:42',
    identitySourceProvider: 'athena_backend',
    identityRetrievedAt: DateTime.utc(2026, 9, 5),
    identityResolutionMethod: 'canonical_listing',
    identityExchangeVerified: true,
    identityRiskReady: true,
    athenaPolicyState: state,
  );
}

void main() {
  const service = PortfolioPolicyStateContextService();

  test('explicit full_long position builds backend policy context', () {
    final context = service.buildForPosition(_verifiedPosition());

    expect(context['instrumentId'], 42);
    expect(context['canonicalInstrumentId'], 'instrument:42');
    expect(context['policyState'], 'full_long');
    expect(context['positionPresent'], isTrue);
    expect(context['shares'], 10.0);
    expect(context['identityRiskReady'], isTrue);
    expect(context['identityExchangeVerified'], isTrue);
  });

  test('missing ATHENA policy state fails closed instead of inferring it', () {
    expect(
      () => service.buildForPosition(_verifiedPosition(state: null)),
      throwsA(isA<StateError>()),
    );
  });

  test('policy state survives portfolio position serialization', () {
    final original = _verifiedPosition(
      state: AthenaPortfolioPolicyState.reducedLong,
    );

    final restored = PortfolioPosition.fromJson(original.toJson());

    expect(restored.athenaPolicyState, AthenaPortfolioPolicyState.reducedLong);
    expect(restored.hasExplicitAthenaPolicyState, isTrue);
  });

  test('legacy position without policy state remains readable but unclassified', () {
    final json = _verifiedPosition().toJson()..remove('athenaPolicyState');

    final restored = PortfolioPosition.fromJson(json);

    expect(restored.athenaPolicyState, isNull);
    expect(restored.hasExplicitAthenaPolicyState, isFalse);
  });

  test('flat context requires verified identity and carries no position', () {
    final context = service.buildFlat(
      instrumentId: 42,
      canonicalInstrumentId: 'instrument:42',
      identityRiskReady: true,
      identityExchangeVerified: true,
    );

    expect(context['policyState'], 'flat');
    expect(context['positionPresent'], isFalse);
    expect(context['shares'], 0.0);
  });
}
