import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/auth_session.dart';
import '../models/authenticated_portfolio_position.dart';

class AuthenticatedPortfolioService {
  static const String _defaultBackendUrl = String.fromEnvironment(
    'ATHENA_BACKEND_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
  static const double _maxEconomicValue = 1000000000000;

  AuthenticatedPortfolioService({
    String baseUrl = _defaultBackendUrl,
    http.Client? client,
    AuthSession? session,
  })  : _baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _client = client ?? http.Client(),
        _ownsClient = client == null,
        _session = session ?? AuthSession.instance;

  final String _baseUrl;
  final http.Client _client;
  final bool _ownsClient;
  final AuthSession _session;

  Future<List<AuthenticatedPortfolioPosition>> loadPositions() async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/user/portfolio'),
      headers: _authenticatedHeaders(),
    );
    final payload = _decodeObject(response);
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de cartera sin data válida.');
    }
    final rawPositions = data['positions'];
    if (rawPositions is! List) {
      throw const FormatException('Respuesta de cartera sin positions válidas.');
    }
    return rawPositions
        .map((item) {
          if (item is! Map<String, dynamic>) {
            throw const FormatException('Posición autenticada no válida.');
          }
          return AuthenticatedPortfolioPosition.fromJson(item);
        })
        .toList(growable: false);
  }

  Future<AuthenticatedPortfolioPosition> upsertPosition({
    required String symbol,
    String? exchange,
    required double quantity,
    double? averagePurchasePrice,
  }) async {
    final normalizedSymbol = symbol.trim().toUpperCase();
    final normalizedExchange = exchange?.trim().toUpperCase();
    if (normalizedSymbol.isEmpty || normalizedSymbol.length > 32) {
      throw ArgumentError.value(symbol, 'symbol', 'Símbolo no válido.');
    }
    if (!quantity.isFinite || quantity <= 0 || quantity > _maxEconomicValue) {
      throw ArgumentError.value(quantity, 'quantity', 'Cantidad no válida.');
    }
    if (averagePurchasePrice != null &&
        (!averagePurchasePrice.isFinite ||
            averagePurchasePrice <= 0 ||
            averagePurchasePrice > _maxEconomicValue)) {
      throw ArgumentError.value(
        averagePurchasePrice,
        'averagePurchasePrice',
        'Precio medio no válido.',
      );
    }

    final body = <String, dynamic>{
      'symbol': normalizedSymbol,
      'exchange': normalizedExchange == null || normalizedExchange.isEmpty
          ? null
          : normalizedExchange,
      'quantity': quantity,
      if (averagePurchasePrice != null)
        'averagePurchasePrice': averagePurchasePrice,
    };
    final response = await _client.put(
      Uri.parse('$_baseUrl/api/v1/user/portfolio/positions'),
      headers: _authenticatedHeaders(json: true),
      body: jsonEncode(body),
    );
    final payload = _decodeObject(response);
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de posición sin data válida.');
    }
    return AuthenticatedPortfolioPosition.fromJson(data);
  }

  Future<void> deletePosition(int positionId) async {
    if (positionId <= 0) {
      throw ArgumentError.value(positionId, 'positionId', 'Id no válido.');
    }
    final response = await _client.delete(
      Uri.parse('$_baseUrl/api/v1/user/portfolio/positions/$positionId'),
      headers: _authenticatedHeaders(),
    );
    if (response.statusCode != 204) {
      throw StateError(_errorMessage(response));
    }
  }

  Map<String, String> _authenticatedHeaders({bool json = false}) {
    final token = _session.accessToken?.trim();
    if (!_session.isAuthenticated || token == null || token.isEmpty) {
      throw StateError('Se requiere una sesión ATHENA autenticada.');
    }
    return {
      'Authorization': 'Bearer $token',
      if (json) 'Content-Type': 'application/json',
    };
  }

  Map<String, dynamic> _decodeObject(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw StateError(_errorMessage(response));
    }
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Respuesta ATHENA no válida.');
    }
    return decoded;
  }

  String _errorMessage(http.Response response) {
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic> && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } catch (_) {
      // Do not expose an unparsable backend body to the user.
    }
    return 'La cartera autenticada no pudo completar la operación.';
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}