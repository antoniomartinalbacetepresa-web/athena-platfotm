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
    required String status,
    required String baseCurrency,
    required String quoteCurrency,
    required this.rate,
    required this.observedAt,
    required this.retrievedAt,
    required String sourceProvider,
    this.sourceSymbol,
    required this.historicalPointInTimeEligible,
  })  : status = status.trim().toLowerCase(),
        baseCurrency = _normalizeCurrency(baseCurrency, 'baseCurrency'),
        quoteCurrency = _normalizeCurrency(quoteCurrency, 'quoteCurrency'),
        sourceProvider = _requireSourceProvider(sourceProvider) {
    if (!rate.isFinite || rate <= 0) {
      throw ArgumentError.value(rate, 'rate', 'La tasa FX debe ser positiva y finita.');
    }
    if (retrievedAt.isBefore(observedAt)) {
      throw ArgumentError(
        'La recuperación FX no puede preceder a la observación.',
      );
    }
    final normalizedStatus = this.status;
    const allowedStatuses = {
      'fx_current_ready',
      'fx_identity',
      'fx_historical_ready',
      'fx_historical_identity',
    };
    if (!allowedStatuses.contains(normalizedStatus)) {
      throw ArgumentError('El estado FX no acredita una cotización válida.');
    }
    final isHistoricalStatus = normalizedStatus == 'fx_historical_ready' ||
        normalizedStatus == 'fx_historical_identity';
    if (historicalPointInTimeEligible != isHistoricalStatus) {
      throw ArgumentError(
        'El estado FX y la elegibilidad PIT histórica son inconsistentes.',
      );
    }

    final isIdentityStatus = normalizedStatus == 'fx_identity' ||
        normalizedStatus == 'fx_historical_identity';
    if (isIdentityStatus != (this.baseCurrency == this.quoteCurrency)) {
      throw ArgumentError(
        'El estado FX de identidad no corresponde al par de divisas.',
      );
    }

    final normalizedSourceSymbol = sourceSymbol?.trim().toUpperCase();
    if (this.baseCurrency == this.quoteCurrency) {
      if (rate != 1.0 || this.sourceProvider != 'identity') {
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
      if (this.sourceProvider.toLowerCase() == 'identity') {
        throw ArgumentError(
          'Una cotización de mercado no puede declarar proveedor identity.',
        );
      }
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
    if (historicalPointInTimeEligible) {
      throw StateError(
        'Una observación FX PIT histórica no puede convertir valores actuales.',
      );
    }
    if (!amount.isFinite) {
      throw ArgumentError.value(amount, 'amount', 'El importe debe ser finito.');
    }
    final converted = amount * rate;
    if (!converted.isFinite) {
      throw StateError('La conversión FX excede el rango numérico finito.');
    }
    return converted;
  }

  double convertHistorical(double amount) {
    if (!historicalPointInTimeEligible) {
      throw StateError(
        'Una cotización FX actual no puede convertir costes históricos.',
      );
    }
    if (!amount.isFinite) {
      throw ArgumentError.value(amount, 'amount', 'El importe debe ser finito.');
    }
    final converted = amount * rate;
    if (!converted.isFinite) {
      throw StateError('La conversión FX histórica excede el rango numérico finito.');
    }
    return converted;
  }

  factory FxQuote.fromMap(Map<String, dynamic> map) {
    if (map['historicalPointInTimeEligible'] is! bool) {
      throw const FormatException(
        'La respuesta FX debe declarar explícitamente su elegibilidad PIT.',
      );
    }
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
    final raw = value?.toString().trim() ?? '';
    if (!RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(raw)) {
      throw FormatException('La respuesta FX contiene $field sin zona horaria.');
    }
    final parsed = DateTime.tryParse(raw);
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

  static String _requireSourceProvider(String value) {
    // Check the raw input before trimming so a trailing control character
    // cannot disappear from the provenance audit boundary.
    if (value.codeUnits.any((unit) => unit < 32 || unit > 126)) {
      throw ArgumentError.value(value, 'sourceProvider', 'Procedencia FX ambigua.');
    }
    final provider = _requireText(value, 'sourceProvider');
    if (provider.contains('%') ||
        provider.contains('&') ||
        provider.contains('\\')) {
      throw ArgumentError.value(value, 'sourceProvider', 'Procedencia FX ambigua.');
    }
    final key = provider.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), '');
    if (key.isEmpty ||
        key.contains('fmp') ||
        key.contains('financialmodelingprep')) {
      throw ArgumentError.value(value, 'sourceProvider', 'Fuente FX prohibida.');
    }
    return provider.toLowerCase() == 'identity' ? 'identity' : provider;
  }

  static String _requireText(String? value, String field) {
    final normalized = value?.trim() ?? '';
    if (normalized.isEmpty) {
      throw ArgumentError.value(value, field, 'No puede estar vacío.');
    }
    return normalized;
  }
}
