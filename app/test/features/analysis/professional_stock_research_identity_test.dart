import 'dart:async';

import 'package:app/features/analysis/presentation/pages/professional_stock_research_page.dart';
import 'package:app/features/recommendations/data/datasources/athena_backend_professional_dossier_data_source.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _PendingDossierSource extends AthenaBackendProfessionalDossierDataSource {
  _PendingDossierSource() : super(baseUrl: 'https://athena.example');

  final Map<String, Completer<ProfessionalDossier>> pending = {};
  final List<String> requested = [];

  @override
  Future<ProfessionalDossier> getLatest({
    DateTime? asOf,
    String? symbol,
    int? instrumentId,
  }) {
    requested.add(symbol!);
    return pending.putIfAbsent(symbol, Completer<ProfessionalDossier>.new).future;
  }
}

ProfessionalDossier _dossier(String symbol, {String? evidenceTag}) => ProfessionalDossier(
      asOf: DateTime.utc(2026, 9, 7),
      symbol: symbol,
      advisoryStatus: 'no_advice',
      productionEligible: false,
      allocationEligible: false,
      executionEligible: false,
      orderRoutingEligible: false,
      automaticTrading: false,
      readOnly: true,
      modules: {
        for (final name in ProfessionalDossier.moduleNames)
          name: ProfessionalModuleState(
            status: 'not_yet_evidenced',
            productionEligible: false,
            reason: 'Evidencia del símbolo ${evidenceTag ?? symbol}',
          ),
      },
    );

void main() {
  testWidgets('research discloses missing evidence and historical cutoff',
      (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    source.pending['AAPL']!.complete(_dossier('AAPL'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Evidencia adjunta: 0 de 11 módulos'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('professional-research-stale-warning')),
        findsOneWidget);
    expect(find.byKey(const Key('professional-research-content')),
        findsOneWidget);
  });

  testWidgets('refresh reissues dossier retrieval without hiding failure',
      (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    expect(source.requested, ['AAPL']);
    await tester.tap(find.byTooltip('Actualizar dossier profesional'));
    await tester.pump();
    expect(source.requested, ['AAPL', 'AAPL']);
    source.pending['AAPL']!.complete(_dossier('AAPL'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('professional-research-content')),
        findsOneWidget);
  });

  testWidgets('a future PIT cutoff from an injected source is rejected',
      (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    final base = _dossier('AAPL');
    source.pending['AAPL']!.complete(ProfessionalDossier(
      asOf: DateTime.now().toUtc().add(const Duration(hours: 1)),
      symbol: 'AAPL',
      advisoryStatus: base.advisoryStatus,
      productionEligible: false,
      allocationEligible: false,
      executionEligible: false,
      orderRoutingEligible: false,
      automaticTrading: false,
      readOnly: true,
      modules: base.modules,
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('professional-research-error')),
        findsOneWidget);
    expect(find.byKey(const Key('professional-research-content')),
        findsNothing);
  });

  testWidgets('changing a research symbol cannot show the old dossier',
      (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    expect(source.requested, ['AAPL']);

    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'MSFT', dataSource: source),
    ));
    await tester.pump();
    expect(source.requested, ['AAPL', 'MSFT']);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    source.pending['MSFT']!.complete(_dossier('MSFT'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Evidencia del símbolo MSFT'), findsWidgets);
    expect(find.textContaining('Evidencia del símbolo AAPL'), findsNothing);

    source.pending['AAPL']!.complete(_dossier('AAPL'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Evidencia del símbolo MSFT'), findsWidgets);
    expect(find.textContaining('Evidencia del símbolo AAPL'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a mismatched dossier from an injected source fails closed',
      (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    source.pending['AAPL']!.complete(_dossier('MSFT'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('professional-research-error')), findsOneWidget);
    expect(find.byKey(const Key('professional-research-content')), findsNothing);
    expect(find.textContaining('Evidencia del símbolo MSFT'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('replacing the research source invalidates its old response',
      (tester) async {
    final oldSource = _PendingDossierSource();
    final newSource = _PendingDossierSource();
    addTearDown(oldSource.dispose);
    addTearDown(newSource.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: oldSource),
    ));
    await tester.pump();

    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: newSource),
    ));
    await tester.pump();
    expect(newSource.requested, ['AAPL']);

    newSource.pending['AAPL']!.complete(_dossier('AAPL', evidenceTag: 'NEW'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Evidencia del símbolo NEW'), findsWidgets);

    oldSource.pending['AAPL']!.complete(_dossier('AAPL', evidenceTag: 'OLD'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Evidencia del símbolo NEW'), findsWidgets);
    expect(find.textContaining('Evidencia del símbolo OLD'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets('el dossier profesional muestra métricas históricas sin inventar datos', (tester) async {
    final source = _PendingDossierSource();
    addTearDown(source.dispose);
    await tester.pumpWidget(MaterialApp(
      home: ProfessionalStockResearchPage(symbol: 'AAPL', dataSource: source),
    ));
    await tester.pump();
    final base = _dossier('AAPL');
    final modules = Map<String, ProfessionalModuleState>.from(base.modules);
    modules['dividendTotalReturn'] = const ProfessionalModuleState(
      status: 'diagnostic_evidence_available',
      productionEligible: false,
      reason: 'Diagnóstico PIT sin autoridad',
      dividendDiagnostics: ProfessionalDividendDiagnostics(
        status: 'diagnostic_ready',
        frequency: 'quarterly',
        trailingYield: 0.02,
        totalReturn60d: -0.05,
      ),
    );
    source.pending['AAPL']!.complete(ProfessionalDossier(
      asOf: base.asOf,
      symbol: 'AAPL',
      advisoryStatus: 'no_advice',
      productionEligible: false,
      allocationEligible: false,
      executionEligible: false,
      orderRoutingEligible: false,
      automaticTrading: false,
      readOnly: true,
      modules: modules,
    ));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('professional-research-safety-boundary')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('professional-research-module-dividendTotalReturn')),
      250,
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('professional-dividend-status')), findsOneWidget);
    expect(find.text('Rentabilidad por dividendo histórica: 2.00 %'), findsOneWidget);
    expect(find.text('Retorno total histórico 60 días: -5.00 %'), findsOneWidget);
    expect(find.text('Payout sobre beneficios: No disponible'), findsOneWidget);
    expect(find.byKey(const Key('professional-research-module-dividendTotalReturn')), findsOneWidget);
  });

}
