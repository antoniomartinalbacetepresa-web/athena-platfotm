import 'package:flutter/material.dart';

import '../../domain/models/stock_analysis_data.dart';
import '../../domain/models/stock_analysis_result.dart';
import '../../domain/services/stock_analysis_engine.dart';

class StockAnalysisTestPage extends StatelessWidget {
  const StockAnalysisTestPage({super.key});

  @override
  Widget build(BuildContext context) {
    const data = StockAnalysisData(
      symbol: 'ATH',
      companyName: 'Athena Test Company',

      currentPrice: 125.40,
      previousClose: 122.80,

      peRatio: 18.5,
      forwardPeRatio: 16.2,
      pegRatio: 1.1,

      revenueGrowth: 12.5,
      earningsGrowth: 18.0,
      epsGrowth: 15.5,

      grossMargin: 48.0,
      operatingMargin: 19.0,
      profitMargin: 14.0,
      returnOnEquity: 21.0,

      totalDebt: 3000,
      totalCash: 5200,
      debtToEquity: 0.45,
      currentRatio: 1.8,

      freeCashFlow: 1800,

      movingAverage50: 118.0,
      movingAverage200: 105.0,
      relativeStrengthIndex: 57,

      beta: 0.95,

      sector: 'Technology',
      industry: 'Software',
      country: 'United States',

      sources: [
        'Test Data',
      ],
    );

    const engine = StockAnalysisEngine();

    final StockAnalysisResult result = engine.analyze(data);

    return Scaffold(
      backgroundColor: const Color(0xFF081423),
      appBar: AppBar(
        backgroundColor: const Color(0xFF081423),
        foregroundColor: Colors.white,
        title: const Text('PRUEBA DEL MOTOR ATHENA'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${result.companyName} (${result.symbol})',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 24,
                fontWeight: FontWeight.bold,
              ),
            ),

            const SizedBox(height: 24),

            _ResultCard(
              title: 'ATHENA SCORE',
              value: '${result.score.toStringAsFixed(1)}/100',
            ),

            const SizedBox(height: 12),

            _ResultCard(
              title: 'CONFIANZA',
              value: '${result.confidence.toStringAsFixed(1)}%',
            ),

            const SizedBox(height: 12),

            _ResultCard(
              title: 'RECOMENDACIÓN',
              value: result.recommendationLabel,
            ),

            const SizedBox(height: 24),

            _SectionTitle(
              title: 'RESUMEN',
            ),

            const SizedBox(height: 8),

            Text(
              result.summary,
              style: const TextStyle(
                color: Color(0xFF9FB2C7),
                fontSize: 15,
                height: 1.5,
              ),
            ),

            const SizedBox(height: 24),

            _SectionTitle(
              title: 'ÁREAS DE ANÁLISIS',
            ),

            const SizedBox(height: 12),

            _AnalysisRow(
              title: 'Fundamentales',
              result: result.fundamentalAnalysis,
            ),

            _AnalysisRow(
              title: 'Valoración',
              result: result.valuationAnalysis,
            ),

            _AnalysisRow(
              title: 'Crecimiento',
              result: result.growthAnalysis,
            ),

            _AnalysisRow(
              title: 'Rentabilidad',
              result: result.profitabilityAnalysis,
            ),

            _AnalysisRow(
              title: 'Salud financiera',
              result: result.financialHealthAnalysis,
            ),

            _AnalysisRow(
              title: 'Análisis técnico',
              result: result.technicalAnalysis,
            ),

            _AnalysisRow(
              title: 'Riesgo',
              result: result.riskAnalysis,
            ),

            const SizedBox(height: 24),

            _SectionTitle(
              title: 'PUNTOS POSITIVOS',
            ),

            const SizedBox(height: 12),

            ...result.strengths.map(
              (strength) => _Bullet(
                text: strength,
                positive: true,
              ),
            ),

            const SizedBox(height: 24),

            _SectionTitle(
              title: 'RIESGOS',
            ),

            const SizedBox(height: 12),

            ...result.risks.map(
              (risk) => _Bullet(
                text: risk,
                positive: false,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  final String title;
  final String value;

  const _ResultCard({
    required this.title,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF11253C),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFF29445F),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: Color(0xFF9FB2C7),
              fontSize: 13,
              fontWeight: FontWeight.bold,
              letterSpacing: 1,
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              color: Color(0xFFD4AF37),
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;

  const _SectionTitle({
    required this.title,
  });

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: const TextStyle(
        color: Colors.white,
        fontSize: 17,
        fontWeight: FontWeight.bold,
        letterSpacing: 0.8,
      ),
    );
  }
}

class _AnalysisRow extends StatelessWidget {
  final String title;
  final AnalysisComponentResult result;

  const _AnalysisRow({
    required this.title,
    required this.result,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF11253C),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Text(
            result.score.toStringAsFixed(0),
            style: const TextStyle(
              color: Color(0xFFD4AF37),
              fontWeight: FontWeight.bold,
              fontSize: 17,
            ),
          ),
        ],
      ),
    );
  }
}

class _Bullet extends StatelessWidget {
  final String text;
  final bool positive;

  const _Bullet({
    required this.text,
    required this.positive,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            positive ? '✓' : '!',
            style: TextStyle(
              color: positive
                  ? const Color(0xFF18C964)
                  : const Color(0xFFFF4D4F),
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: Color(0xFF9FB2C7),
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}