import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/analysis/domain/models/technical_analysis_data.dart';

void main() {
  test(
    'TechnicalAnalysisData almacena correctamente los indicadores técnicos',
    () {
      final startDate = DateTime(2026, 1, 1);
      final endDate = DateTime(2026, 3, 31);

      final result = TechnicalAnalysisData(
        movingAverage20: 200.0,
        movingAverage50: 195.0,
        movingAverage200: 180.0,
        priceAboveMovingAverage20: true,
        priceAboveMovingAverage50: true,
        priceAboveMovingAverage200: true,
        movingAverage50Slope: 0.25,
        movingAverage200Slope: 0.10,
        relativeStrengthIndex: 58.0,
        macd: 4.2,
        macdSignal: 3.8,
        macdHistogram: 0.4,
        macdAboveSignal: true,
        averageVolume20: 45000000,
        relativeVolume: 1.35,
        historicalVolatility: 0.28,
        averageTrueRange14: 5.2,
        periodHigh: 220.0,
        periodLow: 165.0,
        distanceFromPeriodHighPercent: -4.55,
        distanceFromPeriodLowPercent: 21.21,
        supportLevel: 190.0,
        resistanceLevel: 220.0,
        observationsUsed: 60,
        analysisStartDate: startDate,
        analysisEndDate: endDate,
      );

      expect(result.movingAverage20, 200.0);
      expect(result.movingAverage50, 195.0);
      expect(result.movingAverage200, 180.0);

      expect(result.priceAboveMovingAverage20, true);
      expect(result.priceAboveMovingAverage50, true);
      expect(result.priceAboveMovingAverage200, true);

      expect(result.movingAverage50Slope, 0.25);
      expect(result.movingAverage200Slope, 0.10);

      expect(result.relativeStrengthIndex, 58.0);

      expect(result.macd, 4.2);
      expect(result.macdSignal, 3.8);
      expect(result.macdHistogram, 0.4);
      expect(result.macdAboveSignal, true);

      expect(result.averageVolume20, 45000000);
      expect(result.relativeVolume, 1.35);

      expect(result.historicalVolatility, 0.28);
      expect(result.averageTrueRange14, 5.2);

      expect(result.periodHigh, 220.0);
      expect(result.periodLow, 165.0);

      expect(
        result.distanceFromPeriodHighPercent,
        -4.55,
      );

      expect(
        result.distanceFromPeriodLowPercent,
        21.21,
      );

      expect(result.supportLevel, 190.0);
      expect(result.resistanceLevel, 220.0);

      expect(result.observationsUsed, 60);
      expect(result.analysisStartDate, startDate);
      expect(result.analysisEndDate, endDate);

      expect(result.hasData, true);
    },
  );

  test(
    'TechnicalAnalysisData sin indicadores no tiene datos',
    () {
      const result = TechnicalAnalysisData();

      expect(result.hasData, false);
      expect(result.observationsUsed, 0);
    },
  );

  test(
    'copyWith conserva los valores que no se modifican',
    () {
      const original = TechnicalAnalysisData(
        movingAverage50: 195.0,
        relativeStrengthIndex: 58.0,
        relativeVolume: 1.20,
        observationsUsed: 50,
      );

      final updated = original.copyWith(
        relativeStrengthIndex: 65.0,
      );

      expect(updated.movingAverage50, 195.0);
      expect(updated.relativeStrengthIndex, 65.0);
      expect(updated.relativeVolume, 1.20);
      expect(updated.observationsUsed, 50);
    },
  );
}