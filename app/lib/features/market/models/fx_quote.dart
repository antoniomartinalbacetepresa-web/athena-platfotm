class FxQuote {
  final String status;
  final String baseCurrency;
  final String quoteCurrency;
  final double rate;
  final DateTime observedAt;
  final DateTime retrievedAt;
  final String sourceProvider;
  final String? sourceSymbol;
  final bool historicalPointInTimeEligible;

  FxQuote({
    required this.status,
    required String baseCurrency,
    required String quoteCurrency,
    required this.rate,
    required this.observedAt,
    required this.retrievedAt,
    required String sourceProvider,
    this.sourceSymbol,
    required this.historicalPointInTimeEligible,
  })  : baseCurrency = _normalizeCurrency(baseCurrency, 'baseCurrency'),
        quoteCurrency = _normalizeCurrency(quoteCurrency, 'quoteCurrency'),
        sourceProvider = _requireText(sourceProvider, 'sourceProvider') {
    if (!rate.isFinite || rate <= 0) {
      throw ArgumentError.value(rate, 'rate', 'La tasa FX debe ser positiva y finita.');
    }
    if (observedAt.timeZoneOffset == Duration.zero &&
        retrievedAt.isBefore(observedAt)) {
      throw ArgumentError(
        'La recuperación FX no puede preceder a la observación.',
      );
    }
    if (retrievedAt.isBefore(observedAt)) {
      throw ArgumentError(
        'La recuperación FX no puede preceder a la observación.',
      );
    }
    if (historicalPointInTimeEligible) {
      throw ArgumentError(
        'El contrato FX actual de ATHENA no puede declararse elegible como PIT histórico.',
      );
    }

    final normalizedSourceSymbol = sourceSymbol?.trim().toUpperCase();
    if (this.baseCurrency == this.quoteCurrency) {
      if (rate != 1.0 || sourceProvider != 'identity') {
        throw ArgumentError(
          'Una conversión de identidad debe usar tasa 1 y proveedor identity.',
        );
      }
      if (normalizedSourceSymbol != null && normalizedSourceSymbol.isNotEmpty) {
        throw ArgumentError(
          'Una conversión de identidad no debe declarar símbolo de mercado.',
        );
      }
    } else {
      final expectedSymbol = '${this.baseCurrency}${this.quoteCurrency}=X';
      if (normalizedSourceSymbol == null || normalizedSourceSymbol != expectedSymbol) {
        throw ArgumentError(
          'El símbolo FX no corresponde al par solicitado.',
        );
      }
    }
  }

  bool get isIdentity => baseCurrency == quoteCurrency;

  double convertCurrent(double amount) {
    if (!amount.isFinite) {
      throw ArgumentError.value(amount, 'amount', 'El importe debe ser finito.');
    }
    return amount * rate;
  }

  factory FxQuote.fromMap(Map<String, dynamic> map) {
    final observedAt = _parseTimestamp(map['observedAt'], 'observedAt');
    final retrievedAt = _parseTimestamp(map['retrievedAt'], 'retrievedAt');
    final rate = _parseRate(map['rate']);

    return FxQuote(
      status: _requireText(map['status']?.toString(), 'status'),
      baseCurrency: map['baseCurrency']?.toString() ?? '',
      quoteCurrency: map['quoteCurrency']?.toString() ?? '',
      rate: rate,
      observedAt: observedAt,
      retrievedAt: retrievedAt,
      sourceProvider: map['sourceProvider']?.toString() ?? '',
      sourceSymbol: map['sourceSymbol']?.toString(),
      historicalPointInTimeEligible:
          map['historicalPointInTimeEligible'] == true,
    );
  }

  static double _parseRate(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }
    final parsed = double.tryParse(value?.toString() ?? '');
    if (parsed == null) {
      throw const FormatException('La respuesta FX no contiene una tasa numérica.');
    }
    return parsed;
  }

  static DateTime _parseTimestamp(dynamic value, String field) {
    final parsed = DateTime.tryParse(value?.toString() ?? '');
    if (parsed == null) {
      throw FormatException('La respuesta FX contiene $field inválido.');
    }
    if (!parsed.isUtc) {
      return parsed.toUtc();
    }
    return parsed;
  }

  static String _normalizeCurrency(String value, String field) {
    final normalized = value.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(normalized)) {
      throw ArgumentError.value(value, field, 'Debe ser un código ISO de tres letras.');
    }
    return normalized;
  }

  static String _requireText(String? value, String field) {
    final normalized = value?.trim() ?? '';
    if (normalized.isEmpty) {
      throw ArgumentError.value(value, field, 'No puede estar vacío.');
    }
    return normalized;
  }
}
