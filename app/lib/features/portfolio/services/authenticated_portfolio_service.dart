import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/athena_auth_service.dart';
import '../../auth/services/auth_session.dart';
import '../../market/models/market_quote.dart';
import '../../market/repositories/market_repository.dart';
import '../models/authenticated_portfolio_history.dart';
import '../models/authenticated_portfolio_position.dart';

class AuthenticatedPortfolioValuedPosition {
  const AuthenticatedPortfolioValuedPosition({
    required this.holding,
    required this.quote,
  });

  final AuthenticatedPortfolioPosition holding;
  final MarketQuote quote;

  double get currentValue => holding.quantity * quote.currentPrice;

  double? get investedValue => holding.averagePurchasePrice == null
      ? null
      : holding.quantity * holding.averagePurchasePrice!;

  double? get profitLoss {
    final invested = investedValue;
    return invested == null ? null : currentValue - invested;
  }

  double? get profitLossPercentage {
    final invested = investedValue;
    final pnl = profitLoss;
    if (invested == null || pnl == null || invested <= 0) return null;
    return (pnl / invested) * 100;
  }
}

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
  int? _lastRejectedStatusCode;

  Future<List<AuthenticatedPortfolioPosition>> loadPositions() async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/api/v1/user/portfolio'),
      headers: _authenticatedHeaders(),
    );
    await _rejectInvalidSession(response);
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

  /// Loads owner-scoped holdings from the authenticated backend and joins them
  /// with current market observations in memory. Personal quantity/cost basis
  /// remains authoritative on the server; quotes are derived market data and
  /// are deliberately not written to a second local portfolio store.
  Future<List<AuthenticatedPortfolioValuedPosition>> loadValuedPositions({
    required MarketRepository marketRepository,
  }) async {
    final holdings = await loadPositions();
    final valued = <AuthenticatedPortfolioValuedPosition>[];

    for (final holding in holdings) {
      final quote = await marketRepository.getQuote(holding.symbol);
      _validateMarketQuote(holding: holding, quote: quote);
      valued.add(
        AuthenticatedPortfolioValuedPosition(holding: holding, quote: quote),
      );
    }

    return List.unmodifiable(valued);
  }

  void _validateMarketQuote({
    required AuthenticatedPortfolioPosition holding,
    required MarketQuote quote,
  }) {
    final expectedSymbol = holding.symbol.trim().toUpperCase();
    final quoteSymbol = quote.symbol.trim().toUpperCase();
    if (expectedSymbol.isEmpty || quoteSymbol != expectedSymbol) {
      throw StateError(
        'La cotización no corresponde a la posición autenticada solicitada.',
      );
    }
    if (!quote.currentPrice.isFinite || quote.currentPrice <= 0) {
      throw StateError('Cotización actual inválida para la cartera autenticada.');
    }
    final provider = quote.sourceProvider?.trim();
    final retrievedAt = quote.retrievedAt;
    if (provider == null || provider.isEmpty || retrievedAt == null) {
      throw StateError(
        'La valoración autenticada requiere provenance de mercado completa.',
      );
    }
    if (retrievedAt.isBefore(quote.updatedAt)) {
      throw StateError(
        'La recuperación de mercado no puede preceder a la observación.',
      );
    }
    final holdingExchange = holding.exchange?.trim().toUpperCase();
    final quoteExchange = quote.exchange?.trim().toUpperCase();
    if (holdingExchange != null &&
        holdingExchange.isNotEmpty &&
        (quoteExchange == null ||
            quoteExchange.isEmpty ||
            quoteExchange != holdingExchange)) {
      throw StateError(
        'La cotización pertenece a un listing distinto de la posición autenticada.',
      );
    }
  }

  Future<AuthenticatedPortfolioHistory> loadHistory({
    String portfolioId = 'primary',
    DateTime? asOf,
    int limit = 100,
  }) async {
    final normalizedPortfolioId = portfolioId.trim();
    if (normalizedPortfolioId.isEmpty || normalizedPortfolioId.length > 128) {
      throw ArgumentError.value(
        portfolioId,
        'portfolioId',
        'Portfolio id no válido.',
      );
    }
    if (limit < 1 || limit > 500) {
      throw ArgumentError.value(limit, 'limit', 'Limit debe estar entre 1 y 500.');
    }
    final cutoff = (asOf ?? DateTime.now()).toUtc();
    final uri = Uri.parse('$_baseUrl/api/v1/user/portfolio/history').replace(
      queryParameters: {
        'portfolioId': normalizedPortfolioId,
        'asOf': cutoff.toIso8601String(),
        'limit': '$limit',
      },
    );
    final response = await _client.get(uri, headers: _authenticatedHeaders());
    await _rejectInvalidSession(response);
    final payload = _decodeObject(response);
    final data = payload['data'];
    if (data is! Map<String, dynamic>) {
      throw const FormatException('Respuesta de historial sin data válida.');
    }
    return AuthenticatedPortfolioHistory.fromJson(data);
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
      'averagePurchasePrice': ?averagePurchasePrice,
    };
    final response = await _client.put(
      Uri.parse('$_baseUrl/api/v1/user/portfolio/positions'),
      headers: _authenticatedHeaders(json: true),
      body: jsonEncode(body),
    );
    await _rejectInvalidSession(response);
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
    await _rejectInvalidSession(response);
    if (response.statusCode != 204) {
      throw StateError(_errorMessage(response));
    }
  }

  Map<String, String> _authenticatedHeaders({bool json = false}) {
    final token = _session.accessToken?.trim();
    if (!_session.isAuthenticated || token == null || token.isEmpty) {
      final rejectedStatusCode = _lastRejectedStatusCode;
      if (rejectedStatusCode != null) {
        throw AuthSessionRejectedException(rejectedStatusCode);
      }
      throw StateError('Se requiere una sesión ATHENA autenticada.');
    }
    return {
      'Authorization': 'Bearer $token',
      if (json) 'Content-Type': 'application/json',
    };
  }

  Future<void> _rejectInvalidSession(http.Response response) async {
    if (response.statusCode != 401 && response.statusCode != 403) return;
    _lastRejectedStatusCode = response.statusCode;
    // Remote rejection revokes in-memory authority synchronously. Durable token
    // cleanup must not block propagation of that authoritative 401/403 boundary;
    // a stale durable token is revalidated before it can regain authority.
    unawaited(_session.clearAfterRemoteInvalidation());
    throw AuthSessionRejectedException(response.statusCode);
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