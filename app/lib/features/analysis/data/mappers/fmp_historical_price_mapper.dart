import '../../domain/models/market/historical_price.dart';

/// Convierte datos históricos procedentes de Financial Modeling Prep
/// al modelo independiente de proveedor utilizado por ATHENA TYCHE.
///
/// Responsabilidad exclusiva:
/// - transformar JSON de FMP en HistoricalPrice.
///
/// Este mapper NO:
/// - calcula indicadores técnicos,
/// - interpreta tendencias,
/// - genera señales,
/// - calcula puntuaciones,
/// - genera recomendaciones.
class FmpHistoricalPriceMapper {
  const FmpHistoricalPriceMapper();

  /// Convierte una observación histórica de FMP.
  ///
  /// Admite fechas en formato:
  /// - YYYY-MM-DD
  /// - DateTime cuando el valor ya ha sido convertido.
  ///
  /// Lanza [FormatException] cuando falta un dato obligatorio
  /// o alguno de los valores no puede convertirse correctamente.
  HistoricalPrice fromHistoricalQuote(
    Map<String, dynamic> json,
  ) {
    final date = _parseDate(json['date']);

    final open = _requiredDouble(
      json['open'],
      fieldName: 'open',
    );

    final high = _requiredDouble(
      json['high'],
      fieldName: 'high',
    );

    final low = _requiredDouble(
      json['low'],
      fieldName: 'low',
    );

    final close = _requiredDouble(
      json['close'],
      fieldName: 'close',
    );

    final volume = _requiredDouble(
      json['volume'],
      fieldName: 'volume',
    );

    final adjustedClose = _optionalDouble(
      json['adjClose'],
    );

    return HistoricalPrice(
      date: date,
      open: open,
      high: high,
      low: low,
      close: close,
      volume: volume,
      adjustedClose: adjustedClose,
    );
  }

  /// Convierte una lista completa de observaciones históricas.
  ///
  /// Las observaciones se devuelven ordenadas cronológicamente
  /// de más antigua a más reciente.
  List<HistoricalPrice> fromHistoricalQuotes(
    List<dynamic> jsonList,
  ) {
    final prices = <HistoricalPrice>[];

    for (final item in jsonList) {
      if (item is! Map) {
        throw const FormatException(
          'Una observación histórica de FMP tiene un formato inesperado.',
        );
      }

      final json = Map<String, dynamic>.from(item);

      prices.add(
        fromHistoricalQuote(json),
      );
    }

    prices.sort(
      (a, b) => a.date.compareTo(b.date),
    );

    return List.unmodifiable(prices);
  }

  DateTime _parseDate(dynamic value) {
    if (value is DateTime) {
      return value;
    }

    if (value is String) {
      final normalized = value.trim();

      if (normalized.isEmpty) {
        throw const FormatException(
          'El campo date no puede estar vacío.',
        );
      }

      final parsed = DateTime.tryParse(normalized);

      if (parsed != null) {
        return parsed;
      }
    }

    throw const FormatException(
      'El campo date de FMP no tiene un formato válido.',
    );
  }

  double _requiredDouble(
    dynamic value, {
    required String fieldName,
  }) {
    final result = _optionalDouble(value);

    if (result == null) {
      throw FormatException(
        'El campo $fieldName es obligatorio y debe ser numérico.',
      );
    }

    return result;
  }

  double? _optionalDouble(dynamic value) {
    if (value is num) {
      return value.toDouble();
    }

    if (value is String) {
      final normalized = value.trim();

      if (normalized.isEmpty) {
        return null;
      }

      return double.tryParse(normalized);
    }

    return null;
  }
}