import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/market_data_point.dart';
import '../models/persisted_market_history.dart';
import 'market_data_provider.dart';

/// Proveedor de datos de mercado procedentes del backend de ATHENA TYCHE.
///
/// Flutter no conoce ni expone claves de proveedores externos. El backend sí
/// puede declarar la fuente real utilizada, identidad básica del listing y el
/// instante de recuperación para conservar provenance sin acoplar la aplicación
/// cliente al proveedor.
class AthenaBackendMarketDataProvider implements MarketDataProvider {
  static const String _providerId = 'athena_backend';

  final String baseUrl;
  final http.Client client;
  final Duration requestTimeout;

  AthenaBackendMarketDataProvider({
    required this.baseUrl,
    http.Client? client,
    this.requestTimeout = const Duration(seconds: 15),
  }) : assert(requestTimeout > Duration.zero),
       client = client ?? http.Client();

  @override
  String get providerId => _providerId;

  @override
  Future<MarketDataPoint?> getQuote(String symbol) async {
    final normalizedSymbol = _normalizeSymbol(symbol);

    final uri = Uri.parse(
      '$baseUrl/api/v1/market/quote',
    ).replace(queryParameters: {'symbol': normalizedSymbol});

    final response = await client.get(uri).timeout(requestTimeout);
    _validateResponse(response);

    final decoded = _decodeObject(response.body);
    // An explicit null means the provider has no quote. A missing field is
    // a broken API contract and must not be presented as ordinary absence.
    if (!decoded.containsKey('data')) {
      throw const FormatException(
        'El backend no proporcionó el campo data de la cotización.',
      );
    }
    final data = decoded['data'];

    if (data == null) {
      return null;
    }
    if (data is! Map) {
      throw const FormatException(
        'La respuesta del backend no contiene una cotización válida.',
      );
    }

    // A quote without a usable close is not a price. Do not render an
    // apparently successful Market observation with no valuation anchor.
    final quote = _mapPoint(
      data: Map<String, dynamic>.from(data),
      fallbackSymbol: normalizedSymbol,
    );
    if (quote.close == null) {
      throw const FormatException(
        'La cotización no contiene un precio de cierre válido.',
      );
    }
    return quote;
  }

  @override
  Future<List<MarketDataPoint>> getHistoricalData({
    required String symbol,
    DateTime? from,
    DateTime? to,
  }) async {
    final normalizedSymbol = _normalizeSymbol(symbol);
    // Reject inverted ranges before contacting the backend: otherwise a broken
    // historical window could appear as a legitimate empty market history.
    if (from != null && to != null &&
        _formatDate(from).compareTo(_formatDate(to)) > 0) {
      throw ArgumentError.value(to, 'to', 'La fecha final precede a la inicial.');
    }
    final queryParameters = <String, String>{'symbol': normalizedSymbol};

    if (from != null) {
      queryParameters['from'] = _formatDate(from);
    }
    if (to != null) {
      queryParameters['to'] = _formatDate(to);
    }

    final uri = Uri.parse(
      '$baseUrl/api/v1/market/history',
    ).replace(queryParameters: queryParameters);

    final response = await client.get(uri).timeout(requestTimeout);
    _validateResponse(response);

    final decoded = _decodeObject(response.body);
    final data = decoded['data'];

    if (data == null) {
      // Missing history is not evidence of a legitimate empty trading window.
      // Preserve the failure for Market/Radar rather than silently hiding a
      // broken or incompatible backend contract as zero observations.
      throw const FormatException(
        'El backend no proporcionó el campo data del histórico de mercado.',
      );
    }
    if (data is! List) {
      throw const FormatException(
        'La respuesta histórica del backend no contiene una lista válida.',
      );
    }

    final result = <MarketDataPoint>[];
    // Duplicate sessions can inflate volume, returns and chart observations.
    // Reject them instead of silently selecting an arbitrary provider value.
    final observedInstants = <DateTime>{};
    final observedSessions = <String>{};
    DateTime? previousInstant;
    String? previousSession;
    for (final item in data) {
      if (item is! Map) {
        throw const FormatException(
          'El histórico contiene una observación que no es un objeto válido.',
        );
      }
      final point = _mapPoint(
        data: Map<String, dynamic>.from(item),
        fallbackSymbol: normalizedSymbol,
      );
      // A bar without a close cannot support historical returns or Radar.
      // Fail the whole window rather than silently treating a partial bar
      // as a valid price observation.
      if (point.close == null) {
        throw const FormatException(
          'El histórico contiene una observación sin cierre válido.',
        );
      }
      final instant = point.timestamp.toUtc();
      // A provider must not silently expand the requested historical window.
      // Compare calendar dates as sent to the backend, not local instants.
      final sessionDate = point.priceSessionDate ?? _formatDate(point.timestamp);
      if ((from != null && sessionDate.compareTo(_formatDate(from)) < 0) ||
          (to != null && sessionDate.compareTo(_formatDate(to)) > 0)) {
        throw const FormatException(
          'El histórico contiene una sesión fuera del intervalo solicitado.',
        );
      }
      // Session dates must also be monotonic: timezone offsets and delayed
      // publication can make UTC instants increase while trading sessions
      // regress, corrupting chart and return ordering.
      if (previousSession != null && sessionDate.compareTo(previousSession) < 0) {
        throw const FormatException(
          'El histórico contiene sesiones fuera de orden cronológico.',
        );
      }
      previousSession = sessionDate;
      if (previousInstant != null && instant.isBefore(previousInstant)) {
        throw const FormatException(
          'El histórico contiene observaciones fuera de orden cronológico.',
        );
      }
      previousInstant = instant;
      if (!observedSessions.add(sessionDate)) {
        throw const FormatException(
          'El histórico contiene varias barras para una misma sesión.',
        );
      }
      if (!observedInstants.add(instant)) {
        throw const FormatException(
          'El histórico contiene observaciones duplicadas para el mismo instante.',
        );
      }
      result.add(point);
    }
    return result;
  }

  /// Explicit local replay. Never falls back to current provider history.
  Future<PersistedMarketHistory> getPersistedHistoricalData({
    required int instrumentId,
    required String symbol,
    required String sourceProvider,
    required DateTime observedFrom,
    required DateTime observedTo,
    required DateTime asOf,
    int limit = 400,
  }) async {
    final normalizedSymbol = _normalizeSymbol(symbol);
    if (instrumentId <= 0 || sourceProvider.trim().isEmpty ||
        sourceProvider != sourceProvider.trim() || limit < 1 || limit > 400 ||
        observedFrom.isAfter(observedTo) || observedTo.isAfter(asOf) ||
        observedTo.difference(observedFrom) > const Duration(days: 366)) {
      throw ArgumentError('Selección de histórico persistido inválida.');
    }
    final uri = Uri.parse('$baseUrl/api/v1/market/history/persisted').replace(
      queryParameters: {
        'instrumentId': '$instrumentId', 'sourceProvider': sourceProvider,
        'observedFrom': observedFrom.toUtc().toIso8601String(),
        'observedTo': observedTo.toUtc().toIso8601String(),
        'asOf': asOf.toUtc().toIso8601String(), 'limit': '$limit',
      },
    );
    final response = await client.get(uri).timeout(requestTimeout);
    _validateResponse(response);
    final decoded = _decodeObject(response.body);
    final metadata = decoded['provenance'];
    final data = decoded['data'];
    if (metadata is! Map || data is! List || data.length > limit ||
        metadata['retrievalMode'] != 'persisted_local_history' ||
        metadata['instrumentId'] != instrumentId ||
        metadata['sourceProvider'] != sourceProvider ||
        metadata['licenceVerified'] != false ||
        metadata['historicalPointInTimeEligible'] != false ||
        metadata['productionCoverageClaimed'] != false ||
        metadata['orderExecutionAllowed'] != false ||
        metadata['researchOnly'] != true || metadata['truncated'] is! bool ||
        _parseTimestamp(metadata['asOf']) != asOf.toUtc() ||
        _parseTimestamp(metadata['observedFrom']) != observedFrom.toUtc() ||
        _parseTimestamp(metadata['observedTo']) != observedTo.toUtc()) {
      throw const FormatException('Procedencia del histórico persistido inválida.');
    }
    var evidenceKind = PersistedMarketHistory.parseEvidenceKind(metadata['evidenceKind']);
    if (PersistedMarketHistory.classifySource(sourceProvider) ==
        PersistedMarketEvidenceKind.syntheticFixture) {
      evidenceKind = PersistedMarketEvidenceKind.syntheticFixture;
    }
    final points = <MarketDataPoint>[];
    final observationIds = <int>{};
    DateTime? previous;
    for (final row in data) {
      if (row is! Map) {
        throw const FormatException('Observación persistida inválida.');
      }
      if (PersistedMarketHistory.parseEvidenceKind(row['evidenceKind']) ==
          PersistedMarketEvidenceKind.syntheticFixture) {
        evidenceKind = PersistedMarketEvidenceKind.syntheticFixture;
      }
      final point = _mapPoint(
        data: Map<String, dynamic>.from(row), fallbackSymbol: normalizedSymbol,
      );
      final id = point.observationId;
      if (point.instrumentId != instrumentId ||
          point.sourceProvider != sourceProvider ||
          point.historicalPointInTimeEligible != false ||
          point.realTimePriceVerified != false || point.close == null ||
          id == null || !observationIds.add(id) || point.retrievedAt == null ||
          point.availableAt != point.retrievedAt ||
          point.retrievedAt!.isAfter(asOf) ||
          point.timestamp.isBefore(observedFrom) ||
          point.timestamp.isAfter(observedTo) ||
          (point.sourceTimestamp != null &&
              point.sourceTimestamp!.isAfter(point.retrievedAt!)) ||
          (previous != null && !point.timestamp.isAfter(previous))) {
        throw const FormatException('Identidad o corte temporal incompatible.');
      }
      previous = point.timestamp;
      points.add(point);
    }
    return PersistedMarketHistory(
      points: points, asOf: asOf.toUtc(), truncated: metadata['truncated'] as bool,
      evidenceKind: evidenceKind,
    );
  }

  MarketDataPoint _mapPoint({
    required Map<String, dynamic> data,
    required String fallbackSymbol,
  }) {
    final timestamp = _parseTimestamp(data['timestamp']);
    final retrievedAt = _parseOptionalTimestamp(data['retrievedAt']);
    final observationId = data['observationId'];
    if (observationId != null && (observationId is! int || observationId <= 0)) {
      throw const FormatException('Identificador de observación inválido.');
    }
    // A price cannot be observed after the backend says it was retrieved.
    // Reject inconsistent PIT evidence instead of showing a future quote.
    if (retrievedAt != null && timestamp.isAfter(retrievedAt)) {
      throw const FormatException(
        'La observación de mercado es posterior a su recuperación.',
      );
    }

    final symbol = data['symbol']?.toString().trim().toUpperCase();
    // A missing or different provider symbol must never inherit the requested
    // ticker: doing so would fabricate the identity of a price observation.
    if (symbol == null || symbol.isEmpty || symbol != fallbackSymbol) {
      throw const FormatException(
        'La observación no coincide con el símbolo solicitado.',
      );
    }
    final sessionDate = data['priceSessionDate'];
    if (sessionDate != null &&
        (sessionDate is! String ||
            sessionDate.length != 10 ||
            DateTime.tryParse(sessionDate) == null ||
            DateTime.parse(sessionDate).toIso8601String().substring(0, 10) !=
                sessionDate)) {
      throw const FormatException('Fecha de sesión de mercado inválida.');
    }
    final sourceProvider = _optionalText(data['sourceProvider']);
    final currency = _optionalText(data['currency'])?.toUpperCase();
    // Reject malformed verification flags: coercing them to null would hide a
    // broken backend contract and weaken the provenance boundary.
    for (final field in const [
      'realTimePriceVerified',
      'historicalPointInTimeEligible',
    ]) {
      if (data[field] != null && data[field] is! bool) {
        throw FormatException('Indicador de verificación inválido: $field.');
      }
    }
    final identityStatus = data['canonicalIdentityStatus'];
    final instrumentId = data['instrumentId'];
    if (identityStatus != null &&
        identityStatus != 'unresolved' &&
        identityStatus != 'matched_internal_listing') {
      throw const FormatException('Estado de identidad de mercado desconocido.');
    }
    if ((instrumentId != null &&
            (instrumentId is! int ||
                instrumentId <= 0 ||
                identityStatus != 'matched_internal_listing')) ||
        (identityStatus == 'matched_internal_listing' && instrumentId == null)) {
      throw const FormatException('Identidad interna de mercado contradictoria.');
    }

    // Financial observations must never pass malformed prices or volume into
    // Market, Radar or ATHENA as if they were valid market evidence.
    for (final field in const ['open', 'high', 'low', 'close', 'adjustedClose']) {
      final value = _parseDouble(data[field]);
      if (data[field] != null &&
          (value == null || !value.isFinite || value <= 0)) {
        throw FormatException('Precio de mercado inválido: $field.');
      }
    }
    for (final field in const ['volume', 'change', 'changePercentage']) {
      final value = _parseDouble(data[field]);
      if (data[field] != null &&
          (value == null || !value.isFinite ||
              (field == 'volume' && value < 0))) {
        throw FormatException('Dato de mercado inválido: $field.');
      }
    }

    // Reject internally contradictory OHLC bars instead of displaying an
    // impossible candle as genuine evidence. Adjusted close is intentionally
    // excluded: corporate actions can place it outside the raw daily range.
    final open = _parseDouble(data['open']);
    final high = _parseDouble(data['high']);
    final low = _parseDouble(data['low']);
    final close = _parseDouble(data['close']);
    if (high != null && low != null && high < low) {
      throw const FormatException('Rango OHLC contradictorio: high < low.');
    }
    if (high != null &&
        ((open != null && open > high) || (close != null && close > high))) {
      throw const FormatException('Precio OHLC superior al máximo.');
    }
    if (low != null &&
        ((open != null && open < low) || (close != null && close < low))) {
      throw const FormatException('Precio OHLC inferior al mínimo.');
    }

    return MarketDataPoint(
      symbol: symbol,
      timestamp: timestamp,
      open: _parseDouble(data['open']),
      high: _parseDouble(data['high']),
      low: _parseDouble(data['low']),
      close: _parseDouble(data['close']),
      adjustedClose: _parseDouble(data['adjustedClose']),
      volume: _parseDouble(data['volume']),
      change: _parseDouble(data['change']),
      changePercentage: _parseDouble(data['changePercentage']),
      currency: currency,
      exchange: _optionalText(data['exchange']),
      quoteType: _optionalText(data['quoteType']),
      exchangeTimezone: _optionalText(data['exchangeTimezone']),
      providerId: providerId,
      sourceProvider: sourceProvider,
      retrievedAt: retrievedAt,
      availableAt: _parseOptionalTimestamp(data['availableAt']),
      sourceTimestamp: _parseOptionalTimestamp(data['sourceTimestamp']),
      observationId: observationId as int?,
      quoteMode: _optionalText(data['quoteMode']),
      priceSessionDate: _optionalText(data['priceSessionDate']),
      realTimePriceVerified: data['realTimePriceVerified'] is bool
          ? data['realTimePriceVerified'] as bool : null,
      historicalPointInTimeEligible: data['historicalPointInTimeEligible'] is bool
          ? data['historicalPointInTimeEligible'] as bool : null,
      instrumentId: instrumentId as int?,
      canonicalIdentityStatus: identityStatus as String?,
    );
  }

  String _normalizeSymbol(String symbol) {
    final normalized = symbol.trim().toUpperCase();
    if (normalized.isEmpty) {
      throw ArgumentError.value(
        symbol,
        'symbol',
        'El símbolo no puede estar vacío.',
      );
    }
    return normalized;
  }

  void _validateResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode}.',
      );
    }
  }

  Map<String, dynamic> _decodeObject(String body) {
    final decoded = jsonDecode(body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta del backend de ATHENA TYCHE no es un objeto JSON válido.',
      );
    }
    return decoded;
  }

  double? _parseDouble(dynamic value) {
    if (value == null) {
      return null;
    }
    if (value is num) {
      return value.toDouble();
    }
    return double.tryParse(value.toString());
  }

  String? _optionalText(dynamic value) {
    if (value == null) {
      return null;
    }
    final text = value.toString().trim();
    return text.isEmpty ? null : text;
  }

  DateTime _parseTimestamp(dynamic value) {
    if (value == null) {
      throw const FormatException('El backend no proporcionó fecha/hora.');
    }
    final raw = value.toString().trim();
    if (!RegExp(r'(Z|[+-]\d{2}:\d{2})$', caseSensitive: false).hasMatch(raw)) {
      throw const FormatException(
        'La fecha/hora de mercado requiere zona horaria explícita.',
      );
    }
    // DateTime.tryParse normalizes some out-of-range offsets. Reject those
    // before conversion so invalid provider clocks cannot enter PIT research.
    final offset = RegExp(r'([+-])(\d{2}):(\d{2})$').firstMatch(raw);
    if (offset != null) {
      final hours = int.parse(offset.group(2)!);
      final minutes = int.parse(offset.group(3)!);
      if (hours > 23 || minutes > 59) {
        throw const FormatException('Desfase horario de mercado inválido.');
      }
    }
    final parsed = DateTime.tryParse(raw);
    if (parsed == null) {
      throw FormatException(
        'Fecha/hora inválida recibida del backend: $value',
      );
    }
    return parsed;
  }

  DateTime? _parseOptionalTimestamp(dynamic value) {
    if (value == null) {
      return null;
    }
    return _parseTimestamp(value);
  }

  String _formatDate(DateTime value) {
    final year = value.year.toString().padLeft(4, '0');
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '$year-$month-$day';
  }

  void dispose() {
    client.close();
  }
}
