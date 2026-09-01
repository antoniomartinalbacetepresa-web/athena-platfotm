import 'package:flutter_test/flutter_test.dart';

import 'package:app/features/analysis/domain/models/market/historical_price.dart';
import 'package:app/features/analysis/domain/services/technical_analysis_calculator.dart';

void main() {
  const calculator = TechnicalAnalysisCalculator();

  HistoricalPrice price({
    required int day,
    required double close,
  }) {
    return HistoricalPrice(
      date: DateTime(2026, 1, 1).add(Duration(days: day)),
      open: close,
      high: close,
      low: close,
      close: close,
      volume: 1000,
    );
  }

  List<HistoricalPrice> generatePrices({
    required int count,
    required double Function(int index) close,
  }) {
    return List.generate(
      count,
      (index) => price(
        day: index,
        close: close(index),
      ),
    );
  }

  group('TechnicalAnalysisCalculator', () {
    test('devuelve datos vacíos cuando no existen precios', () {
      final result = calculator.calculate(const []);

      expect(result.movingAverage20, isNull);
      expect(result.movingAverage50, isNull);
      expect(result.movingAverage200, isNull);
      expect(result.observationsUsed, 0);
      expect(result.analysisStartDate, isNull);
      expect(result.analysisEndDate, isNull);
    });

    test('calcula correctamente SMA20', () {
      final prices = generatePrices(
        count: 20,
        close: (index) => (index + 1).toDouble(),
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage20, 10.5);
    });

    test('calcula SMA20 utilizando únicamente las últimas 20 sesiones', () {
      final prices = generatePrices(
        count: 25,
        close: (index) => (index + 1).toDouble(),
      );

      final result = calculator.calculate(prices);

      final expected =
          List.generate(20, (index) => (index + 6).toDouble())
              .reduce((a, b) => a + b) /
          20;

      expect(result.movingAverage20, expected);
    });

    test('devuelve null para SMA50 si hay menos de 50 observaciones', () {
      final prices = generatePrices(
        count: 49,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage50, isNull);
    });

    test('calcula correctamente SMA50', () {
      final prices = generatePrices(
        count: 50,
        close: (index) => (index + 1).toDouble(),
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage50, 25.5);
    });

    test('devuelve null para SMA200 si hay menos de 200 observaciones', () {
      final prices = generatePrices(
        count: 199,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage200, isNull);
    });

    test('calcula correctamente SMA200', () {
      final prices = generatePrices(
        count: 200,
        close: (index) => (index + 1).toDouble(),
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage200, 100.5);
    });

    test('detecta correctamente precio por encima de las medias', () {
      final prices = generatePrices(
        count: 200,
        close: (index) => index < 199 ? 100 : 200,
      );

      final result = calculator.calculate(prices);

      expect(result.priceAboveMovingAverage20, isTrue);
      expect(result.priceAboveMovingAverage50, isTrue);
      expect(result.priceAboveMovingAverage200, isTrue);
    });

    test('detecta correctamente precio por debajo de las medias', () {
      final prices = generatePrices(
        count: 200,
        close: (index) => index < 199 ? 200 : 100,
      );

      final result = calculator.calculate(prices);

      expect(result.priceAboveMovingAverage20, isFalse);
      expect(result.priceAboveMovingAverage50, isFalse);
      expect(result.priceAboveMovingAverage200, isFalse);
    });

    test('devuelve null para comparación con una media insuficiente', () {
      final prices = generatePrices(
        count: 30,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(result.priceAboveMovingAverage20, isFalse);
      expect(result.priceAboveMovingAverage50, isNull);
      expect(result.priceAboveMovingAverage200, isNull);
    });

    test('registra correctamente las observaciones utilizadas', () {
      final prices = generatePrices(
        count: 75,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(result.observationsUsed, 75);
    });

    test('registra correctamente la primera y última fecha', () {
      final prices = generatePrices(
        count: 10,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(
        result.analysisStartDate,
        DateTime(2026, 1, 1),
      );

      expect(
        result.analysisEndDate,
        DateTime(2026, 1, 10),
      );
    });

    test('calcula pendiente positiva cuando el precio aumenta', () {
      final prices = generatePrices(
        count: 50,
        close: (index) => 100.0 + index.toDouble(),
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage50Slope, greaterThan(0));
    });

    test('calcula pendiente negativa cuando el precio disminuye', () {
      final prices = generatePrices(
        count: 50,
        close: (index) => 200.0 - index.toDouble(),
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage50Slope, lessThan(0));
    });

    test('calcula pendiente cero cuando el precio permanece constante', () {
      final prices = generatePrices(
        count: 50,
        close: (_) => 100,
      );

      final result = calculator.calculate(prices);

      expect(result.movingAverage50Slope, 0);
    });

    test('ordena cronológicamente los datos antes de calcular', () {
      final prices = generatePrices(
        count: 20,
        close: (index) => (index + 1).toDouble(),
      ).reversed.toList();

      final result = calculator.calculate(prices);

      expect(result.movingAverage20, 10.5);
      expect(result.analysisStartDate, DateTime(2026, 1, 1));
      expect(result.analysisEndDate, DateTime(2026, 1, 20));
    });
  });
}
