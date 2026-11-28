import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('allocation panel distinguishes portfolio total from candidate position', () {
    final source = File(
      'lib/features/portfolio/widgets/athena_allocation_panel.dart',
    ).readAsStringSync();

    final investedLabel = source.indexOf("'Valor invertido verificable'");
    final investedField = source.indexOf(
      'candidate.investedPositionsValueInBaseCurrency',
      investedLabel,
    );
    expect(investedLabel, greaterThanOrEqualTo(0));
    expect(investedField, greaterThan(investedLabel));
    expect(investedField - investedLabel, lessThan(220));

    final positionLabel = source.indexOf("'Posición del instrumento'");
    final positionField = source.indexOf(
      'candidate.currentPositionValueInBaseCurrency',
      positionLabel,
    );
    expect(positionLabel, greaterThanOrEqualTo(0));
    expect(positionField, greaterThan(positionLabel));
    expect(positionField - positionLabel, lessThan(220));

    expect(source, isNot(contains("'Valor actual cartera'")));
    expect(
      source,
      contains(
        'No representa efectivo, pasivos ni patrimonio neto total.',
      ),
    );
  });

  test('allocation panel exposes both FX knowledge timestamps', () {
    final source = File(
      'lib/features/portfolio/widgets/athena_allocation_panel.dart',
    ).readAsStringSync();

    expect(source, contains('fx.observedAt.toLocal()'));
    expect(source, contains('fx.retrievedAt.toLocal()'));
    expect(source, contains('fx.sourceProvider'));
  });
}
