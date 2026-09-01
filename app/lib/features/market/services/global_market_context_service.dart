import '../models/global_market_context.dart';
import '../models/regional_market_context.dart';
import '../models/regional_market_weights.dart';

/// Construye el contexto global a partir de los contextos regionales.
///
/// Este servicio recibe los pesos regionales ya resueltos por una capa
/// superior y los utiliza para construir el contexto global.
///
/// Los pesos pueden proceder tanto de:
/// - datos calculados;
/// - un baseline provisional.
///
/// Este servicio no decide qué fuente debe utilizarse.
class GlobalMarketContextService {
  const GlobalMarketContextService();

  GlobalMarketContext build({
    required RegionalMarketContext america,
    required RegionalMarketContext europe,
    required RegionalMarketContext asia,
    required double americaWeight,
    required double europeWeight,
    required double asiaWeight,
    RegionalMarketWeightSource weightSource =
        RegionalMarketWeightSource.calculated,
    double weightConfidence = 1.0,
  }) {
    _validateWeights(
      americaWeight: americaWeight,
      europeWeight: europeWeight,
      asiaWeight: asiaWeight,
    );

    _validateConfidence(weightConfidence);

    final advancingPercentage = _weightedAverage(
      america.advancingPercentage,
      europe.advancingPercentage,
      asia.advancingPercentage,
      americaWeight,
      europeWeight,
      asiaWeight,
    );

    final decliningPercentage = _weightedAverage(
      america.decliningPercentage,
      europe.decliningPercentage,
      asia.decliningPercentage,
      americaWeight,
      europeWeight,
      asiaWeight,
    );

    final sentiment = _calculateSentiment(
      america: america,
      europe: europe,
      asia: asia,
      americaWeight: americaWeight,
      europeWeight: europeWeight,
      asiaWeight: asiaWeight,
    );

    return GlobalMarketContext(
      updatedAt: DateTime.now(),
      america: america,
      europe: europe,
      asia: asia,
      americaWeight: americaWeight,
      europeWeight: europeWeight,
      asiaWeight: asiaWeight,
      weightSource: weightSource,
      weightConfidence: weightConfidence,
      advancingPercentage: advancingPercentage,
      decliningPercentage: decliningPercentage,
      sentiment: sentiment,
      summary: _buildSummary(
        sentiment: sentiment,
        weightSource: weightSource,
      ),
    );
  }

  double _weightedAverage(
    double americaValue,
    double europeValue,
    double asiaValue,
    double americaWeight,
    double europeWeight,
    double asiaWeight,
  ) {
    return (americaValue * americaWeight) +
        (europeValue * europeWeight) +
        (asiaValue * asiaWeight);
  }

  String _calculateSentiment({
    required RegionalMarketContext america,
    required RegionalMarketContext europe,
    required RegionalMarketContext asia,
    required double americaWeight,
    required double europeWeight,
    required double asiaWeight,
  }) {
    final score =
        _sentimentScore(america.sentiment) * americaWeight +
        _sentimentScore(europe.sentiment) * europeWeight +
        _sentimentScore(asia.sentiment) * asiaWeight;

    if (score > 0) {
      return 'positive';
    }

    if (score < 0) {
      return 'negative';
    }

    return 'neutral';
  }

  int _sentimentScore(String sentiment) {
    switch (sentiment.toLowerCase()) {
      case 'positive':
        return 1;

      case 'negative':
        return -1;

      default:
        return 0;
    }
  }

  String _buildSummary({
    required String sentiment,
    required RegionalMarketWeightSource weightSource,
  }) {
    final suffix = weightSource ==
            RegionalMarketWeightSource.baseline
        ? ' Los pesos regionales utilizan temporalmente '
            'una referencia estructural.'
        : '';

    switch (sentiment) {
      case 'positive':
        return 'El mercado global presenta un sesgo positivo '
            'según los datos regionales disponibles.$suffix';

      case 'negative':
        return 'El mercado global presenta un sesgo negativo '
            'según los datos regionales disponibles.$suffix';

      default:
        return 'El mercado global presenta un comportamiento mixto '
            'según los datos regionales disponibles.$suffix';
    }
  }

  void _validateWeights({
    required double americaWeight,
    required double europeWeight,
    required double asiaWeight,
  }) {
    final weights = [
      americaWeight,
      europeWeight,
      asiaWeight,
    ];

    if (weights.any((weight) => !weight.isFinite)) {
      throw ArgumentError(
        'Los pesos regionales deben ser valores numéricos finitos.',
      );
    }

    if (weights.any((weight) => weight < 0)) {
      throw ArgumentError(
        'Los pesos regionales no pueden ser negativos.',
      );
    }

    final total =
        americaWeight +
        europeWeight +
        asiaWeight;

    if ((total - 1.0).abs() > 0.000001) {
      throw ArgumentError(
        'Los pesos regionales deben sumar exactamente 1.0.',
      );
    }
  }

  void _validateConfidence(double confidence) {
    if (!confidence.isFinite ||
        confidence < 0 ||
        confidence > 1) {
      throw ArgumentError(
        'La confianza de los pesos regionales '
        'debe encontrarse entre 0 y 1.',
      );
    }
  }
}