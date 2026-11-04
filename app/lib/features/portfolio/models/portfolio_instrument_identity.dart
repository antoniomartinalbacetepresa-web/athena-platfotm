class PortfolioInstrumentIdentity {
  final int databaseInstrumentId;
  final String canonicalInstrumentId;
  final String issuerId;
  final String symbol;
  final String exchange;
  final String exchangeShortName;
  final String currency;
  final String sourceProvider;
  final DateTime retrievedAt;
  final String resolutionMethod;
  final bool exchangeVerified;
  final bool isRiskReady;
  final bool isWeightingReady;
  final String recommendationPolicy;
  final bool productionEligible;
  final bool automaticTrading;

  const PortfolioInstrumentIdentity({
    required this.databaseInstrumentId,
    required this.canonicalInstrumentId,
    required this.issuerId,
    required this.symbol,
    required this.exchange,
    required this.exchangeShortName,
    required this.currency,
    required this.sourceProvider,
    required this.retrievedAt,
    required this.resolutionMethod,
    required this.exchangeVerified,
    required this.isRiskReady,
    required this.isWeightingReady,
    required this.recommendationPolicy,
    required this.productionEligible,
    required this.automaticTrading,
  });

  factory PortfolioInstrumentIdentity.fromMap(Map<String, dynamic> map) {
    final databaseInstrumentId = map['databaseInstrumentId'];
    if (databaseInstrumentId is! int || databaseInstrumentId <= 0) {
      throw const FormatException('databaseInstrumentId inválido.');
    }

    String requiredText(String key) {
      final value = map[key]?.toString().trim() ?? '';
      if (value.isEmpty) throw FormatException('$key es obligatorio.');
      return value;
    }

    bool requiredBool(String key) {
      final value = map[key];
      if (value is! bool) throw FormatException('$key debe ser booleano.');
      return value;
    }

    final symbol = requiredText('symbol').toUpperCase();
    final exchange = requiredText('exchange').toUpperCase();
    final exchangeShortName = requiredText('exchangeShortName').toUpperCase();
    final currency = requiredText('currency').toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw const FormatException('currency no es un código ISO válido.');
    }

    final retrievedAt = DateTime.tryParse(requiredText('retrievedAt'))?.toUtc();
    if (retrievedAt == null) {
      throw const FormatException('retrievedAt no es una fecha ISO válida.');
    }

    final exchangeVerified = requiredBool('exchangeVerified');
    final riskReady = requiredBool('isRiskReady');
    final weightingReady = requiredBool('isWeightingReady');
    final productionEligible = requiredBool('productionEligible');
    final automaticTrading = requiredBool('automaticTrading');
    final recommendationPolicy = requiredText('recommendationPolicy');

    if (riskReady && !exchangeVerified) {
      throw const FormatException(
        'Una identidad apta para riesgo requiere exchange verificado.',
      );
    }
    if (recommendationPolicy != 'no_advice' ||
        productionEligible ||
        automaticTrading) {
      throw const FormatException(
        'La identidad de cartera no puede habilitar advice, producción ni trading.',
      );
    }

    return PortfolioInstrumentIdentity(
      databaseInstrumentId: databaseInstrumentId,
      canonicalInstrumentId: requiredText('canonicalInstrumentId'),
      issuerId: requiredText('issuerId'),
      symbol: symbol,
      exchange: exchange,
      exchangeShortName: exchangeShortName,
      currency: currency,
      sourceProvider: requiredText('sourceProvider'),
      retrievedAt: retrievedAt,
      resolutionMethod: requiredText('resolutionMethod'),
      exchangeVerified: exchangeVerified,
      isRiskReady: riskReady,
      isWeightingReady: weightingReady,
      recommendationPolicy: recommendationPolicy,
      productionEligible: productionEligible,
      automaticTrading: automaticTrading,
    );
  }
}
