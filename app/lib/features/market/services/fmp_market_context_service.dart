import 'dart:convert';

import '../models/market_context.dart';
import 'fmp_market_context_data_source.dart';
import 'market_context_service.dart';

/// Servicio encargado de construir el contexto agregado del mercado.
///
/// Utiliza únicamente datos proporcionados por las fuentes de mercado.
/// No contiene reglas de inversión ni genera recomendaciones.
class FmpMarketContextService implements MarketContextService {
  final FmpMarketContextDataSource dataSource;

  const FmpMarketContextService({
    required this.dataSource,
  });

  @override
  Future<MarketContext> getMarketContext() async {
    final today = _formatDate(DateTime.now());

    final sectorsResponse = await dataSource.getSectorPerformance(
      date: today,
    );

    final gainersResponse = await dataSource.getBiggestGainers();

    final losersResponse = await dataSource.getBiggestLosers();

    _validateResponse(
      sectorsResponse,
      'rendimiento de sectores',
    );

    _validateResponse(
      gainersResponse,
      'mayores ganadores',
    );

    _validateResponse(
      losersResponse,
      'mayores perdedores',
    );

    final sectors = _decodeList(sectorsResponse);
    final gainers = _decodeList(gainersResponse);
    final losers = _decodeList(losersResponse);

    final assetsAnalyzed = gainers.length + losers.length;

    final advancingPercentage = _calculatePercentage(
      numerator: gainers.length,
      denominator: assetsAnalyzed,
    );

    final decliningPercentage = _calculatePercentage(
      numerator: losers.length,
      denominator: assetsAnalyzed,
    );

    final sentiment = _calculateSentiment(
      sectors: sectors,
      advancingPercentage: advancingPercentage,
      decliningPercentage: decliningPercentage,
    );

    return MarketContext(
      updatedAt: DateTime.now(),
      assetsAnalyzed: assetsAnalyzed,
      advancingPercentage: advancingPercentage,
      decliningPercentage: decliningPercentage,
      volatility: null,
      sentiment: sentiment,
      summary: _buildSummary(sentiment),
    );
  }

  double _calculatePercentage({
    required int numerator,
    required int denominator,
  }) {
    if (denominator == 0) {
      return 0.0;
    }

    return numerator / denominator * 100.0;
  }

  void _validateResponse(
    dynamic response,
    String description,
  ) {
    if (response.statusCode != 200) {
      throw Exception(
        'FMP respondió con código HTTP '
        '${response.statusCode} al obtener $description.',
      );
    }
  }

  List<Map<String, dynamic>> _decodeList(
    dynamic response,
  ) {
    final decoded = jsonDecode(response.body);

    if (decoded is! List) {
      throw FormatException(
        'FMP devolvió un formato inesperado.',
      );
    }

    return decoded
        .whereType<Map>()
        .map(
          (item) => Map<String, dynamic>.from(item),
        )
        .toList();
  }

  String _calculateSentiment({
    required List<Map<String, dynamic>> sectors,
    required double advancingPercentage,
    required double decliningPercentage,
  }) {
    if (sectors.isEmpty) {
      return _sentimentFromBreadth(
        advancingPercentage: advancingPercentage,
        decliningPercentage: decliningPercentage,
      );
    }

    int positiveSectors = 0;
    int negativeSectors = 0;

    for (final sector in sectors) {
      final change = _extractChange(sector);

      if (change == null) {
        continue;
      }

      if (change > 0) {
        positiveSectors++;
      } else if (change < 0) {
        negativeSectors++;
      }
    }

    if (positiveSectors > negativeSectors) {
      return 'positive';
    }

    if (negativeSectors > positiveSectors) {
      return 'negative';
    }

    return _sentimentFromBreadth(
      advancingPercentage: advancingPercentage,
      decliningPercentage: decliningPercentage,
    );
  }

  String _sentimentFromBreadth({
    required double advancingPercentage,
    required double decliningPercentage,
  }) {
    if (advancingPercentage > decliningPercentage) {
      return 'positive';
    }

    if (decliningPercentage > advancingPercentage) {
      return 'negative';
    }

    return 'neutral';
  }

  double? _extractChange(
    Map<String, dynamic> item,
  ) {
    const possibleKeys = [
      'changesPercentage',
      'changePercentage',
      'change',
      'changes',
    ];

    for (final key in possibleKeys) {
      final value = item[key];

      if (value is num) {
        return value.toDouble();
      }

      if (value is String) {
        final parsed = double.tryParse(
          value.replaceAll('%', '').trim(),
        );

        if (parsed != null) {
          return parsed;
        }
      }
    }

    return null;
  }

  String _buildSummary(String sentiment) {
    switch (sentiment) {
      case 'positive':
        return 'El mercado presenta un sesgo positivo '
            'según los datos agregados disponibles.';

      case 'negative':
        return 'El mercado presenta un sesgo negativo '
            'según los datos agregados disponibles.';

      default:
        return 'El mercado presenta un comportamiento '
            'mixto según los datos agregados disponibles.';
    }
  }

  String _formatDate(DateTime date) {
    final year = date.year.toString().padLeft(4, '0');
    final month = date.month.toString().padLeft(2, '0');
    final day = date.day.toString().padLeft(2, '0');

    return '$year-$month-$day';
  }
}