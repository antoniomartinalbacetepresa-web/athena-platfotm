import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/economic_data_point.dart';
import 'economic_data_provider.dart';

/// Proveedor de datos económicos basado en FRED.
///
/// Responsabilidades:
/// - Solicitar series económicas a FRED.
/// - Validar la respuesta recibida.
/// - Convertir las observaciones a EconomicDataPoint.
///
/// La clave API se recibe por inyección y no se almacena
/// dentro del código fuente de ATHENA TYCHE.
class FredEconomicDataProvider implements EconomicDataProvider {
  static const String _providerId = 'fred';
  static const String _defaultBaseUrl =
      'https://api.stlouisfed.org';

  final String apiKey;
  final http.Client client;
  final String baseUrl;

  FredEconomicDataProvider({
    required this.apiKey,
    http.Client? client,
    this.baseUrl = _defaultBaseUrl,
  }) : client = client ?? http.Client();

  @override
  String get providerId => _providerId;

  @override
  Future<List<EconomicDataPoint>> getSeries(
    String seriesId,
  ) async {
    final normalizedSeriesId = seriesId.trim().toUpperCase();

    if (normalizedSeriesId.isEmpty) {
      throw ArgumentError(
        'El identificador de la serie no puede estar vacío.',
      );
    }

    if (apiKey.trim().isEmpty) {
      throw ArgumentError(
        'La clave API de FRED no puede estar vacía.',
      );
    }

    final uri = Uri.parse(
      '$baseUrl/fred/series/observations',
    ).replace(
      queryParameters: {
        'series_id': normalizedSeriesId,
        'api_key': apiKey,
        'file_type': 'json',
      },
    );

    final response = await client.get(uri);

    if (response.statusCode != 200) {
      throw Exception(
        'FRED respondió con código HTTP '
        '${response.statusCode}.',
      );
    }

    final dynamic decoded = jsonDecode(response.body);

    if (decoded is! Map) {
      throw FormatException(
        'La respuesta de FRED tiene un formato inesperado.',
      );
    }

    final observations = decoded['observations'];

    if (observations is! List) {
      throw FormatException(
        'FRED no devolvió una lista de observaciones.',
      );
    }

    final result = <EconomicDataPoint>[];

    for (final observation in observations) {
      if (observation is! Map) {
        continue;
      }

      final dateText = observation['date']?.toString().trim();
      final valueText = observation['value']?.toString().trim();

      if (dateText == null ||
          dateText.isEmpty ||
          valueText == null ||
          valueText.isEmpty) {
        continue;
      }

      final timestamp = DateTime.tryParse(dateText);
      final value = double.tryParse(valueText);

      if (timestamp == null || value == null) {
        continue;
      }

      result.add(
        EconomicDataPoint(
          seriesId: normalizedSeriesId,
          timestamp: timestamp,
          value: value,
          providerId: providerId,
        ),
      );
    }

    return result;
  }

  /// Libera el cliente HTTP cuando el proveedor deja de utilizarse.
  void dispose() {
    client.close();
  }
}
