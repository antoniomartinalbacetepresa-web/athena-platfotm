import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/portfolio/models/portfolio_allocation_target.dart';
import 'package:app/features/portfolio/services/portfolio_allocation_plan_service.dart';

void main() {
  const service = PortfolioAllocationPlanService();

  test('converts validated target weights into amounts and cash reserve', () {
    final plan = service.build(
      referenceCapital: 10000,
      targets: const [
        PortfolioAllocationTarget(
          symbol: 'AAA',
          targetWeight: 0.30,
          sourceRecommendationId: 'rec-aaa',
          evidenceFingerprint: 'fingerprint-aaa',
          productionEligible: true,
        ),
        PortfolioAllocationTarget(
          symbol: 'BBB',
          targetWeight: 0.20,
          sourceRecommendationId: 'rec-bbb',
          evidenceFingerprint: 'fingerprint-bbb',
          productionEligible: true,
        ),
      ],
    );

    expect(plan.lines, hasLength(2));
    expect(plan.lines[0].targetAmount, 3000);
    expect(plan.lines[1].targetAmount, 2000);
    expect(plan.allocatedAmount, 5000);
    expect(plan.cashReserveAmount, 5000);
    expect(plan.cashReserveWeight, 0.5);
  });

  test('rejects any non-production target instead of inferring an allocation', () {
    expect(
      () => service.build(
        referenceCapital: 10000,
        targets: const [
          PortfolioAllocationTarget(
            symbol: 'AAA',
            targetWeight: 0.30,
            sourceRecommendationId: 'rec-aaa',
            evidenceFingerprint: 'fingerprint-aaa',
            productionEligible: false,
          ),
        ],
      ),
      throwsStateError,
    );
  });

  test('rejects missing provenance', () {
    expect(
      () => service.build(
        referenceCapital: 10000,
        targets: const [
          PortfolioAllocationTarget(
            symbol: 'AAA',
            targetWeight: 0.30,
            sourceRecommendationId: '',
            evidenceFingerprint: '',
            productionEligible: true,
          ),
        ],
      ),
      throwsStateError,
    );
  });

  test('rejects duplicate symbols and total weights above one', () {
    expect(
      () => service.build(
        referenceCapital: 10000,
        targets: const [
          PortfolioAllocationTarget(
            symbol: 'AAA',
            targetWeight: 0.20,
            sourceRecommendationId: 'r1',
            evidenceFingerprint: 'f1',
            productionEligible: true,
          ),
          PortfolioAllocationTarget(
            symbol: 'aaa',
            targetWeight: 0.20,
            sourceRecommendationId: 'r2',
            evidenceFingerprint: 'f2',
            productionEligible: true,
          ),
        ],
      ),
      throwsStateError,
    );

    expect(
      () => service.build(
        referenceCapital: 10000,
        targets: const [
          PortfolioAllocationTarget(
            symbol: 'AAA',
            targetWeight: 0.70,
            sourceRecommendationId: 'r1',
            evidenceFingerprint: 'f1',
            productionEligible: true,
          ),
          PortfolioAllocationTarget(
            symbol: 'BBB',
            targetWeight: 0.40,
            sourceRecommendationId: 'r2',
            evidenceFingerprint: 'f2',
            productionEligible: true,
          ),
        ],
      ),
      throwsStateError,
    );
  });

  test('rejects invalid reference capital and empty target sets', () {
    expect(
      () => service.build(referenceCapital: 0, targets: const []),
      throwsArgumentError,
    );

    expect(
      () => service.build(referenceCapital: 10000, targets: const []),
      throwsStateError,
    );
  });
}
