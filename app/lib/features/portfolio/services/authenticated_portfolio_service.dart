import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../auth/services/athena_auth_service.dart';
import '../../auth/services/auth_session.dart';
import '../../market/models/market_quote.dart';
import '../../market/repositories/market_repository.dart';
import '../models/authenticated_portfolio_history.dart';
import '../models/authenticated_portfolio_position.dart';

class AuthenticatedPortfolioAuthorityChangedException implements Exception {
  const AuthenticatedPortfolioAuthorityChangedException();

  @override
  String toString() => 'La autoridad ATHENA cambió durante la operación de cartera.';
}

class AuthenticatedPortfolioValuedPosition {
  const AuthenticatedPortfolioValuedPosition({required this.holding, required this.quote});
  final AuthenticatedPortfolioPosition holding;
  final MarketQuote quote;
  double get currentValue => holding.quantity * quote.currentPrice;
  double? get investedValue => holding.averagePurchasePrice == null ? null : holding.quantity * holding.averagePurchasePrice!;
  double? get profitLoss { final invested = investedValue; return invested == null ? null : currentValue - invested; }
  double? get profitLossPercentage { final invested = investedValue; final pnl = profitLoss; if (invested == null || pnl == null || invested <= 0) return null; return (pnl / invested) * 100; }
}

class AuthenticatedPortfolioService {
  static const String _defaultBackendUrl = String.fromEnvironment('ATHENA_BACKEND_URL', defaultValue: 'http://127.0.0.1:8000');
  static const double _maxEconomicValue = 1000000000000;

  AuthenticatedPortfolioService({String baseUrl = _defaultBackendUrl, http.Client? client, AuthSession? session})
      : _baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''), _client = client ?? http.Client(), _ownsClient = client == null, _session = session ?? AuthSession.instance;

  final String _baseUrl; final http.Client _client; final bool _ownsClient; final AuthSession _session; int? _lastRejectedStatusCode;

  String _currentToken() {
    final token = _session.accessToken?.trim();
    if (!_session.isAuthenticated || token == null || token.isEmpty) {
      final rejected = _lastRejectedStatusCode;
      if (rejected != null) throw AuthSessionRejectedException(rejected);
      throw StateError('Se requiere una sesión ATHENA autenticada.');
    }
    return token;
  }

  /// Captures the authenticated owner boundary for a multi-request operation.
  /// Callers must re-check it before every subsequent request so one logical
  /// operation can never continue under a replacement account.
  String captureAuthorityToken() => _currentToken();

  void requireAuthorityToken(String authorityToken) =>
      _requireCurrentToken(authorityToken);

  Map<String,String> _headersFor(String token,{bool json=false}) => {'Authorization':'Bearer $token', if(json) 'Content-Type':'application/json'};

  Future<List<AuthenticatedPortfolioPosition>> loadPositions() async {
    final token=_currentToken();
    final response=await _client.get(Uri.parse('$_baseUrl/api/v1/user/portfolio'),headers:_headersFor(token));
    await _rejectInvalidSession(response, token);
    _requireCurrentToken(token);
    final data=_decodeObject(response)['data']; if(data is! Map<String,dynamic>) throw const FormatException('Respuesta de cartera sin data válida.');
    final raw=data['positions']; if(raw is! List) throw const FormatException('Respuesta de cartera sin positions válidas.');
    return raw.map((item){if(item is! Map<String,dynamic>) throw const FormatException('Posición autenticada no válida.'); return AuthenticatedPortfolioPosition.fromJson(item);}).toList(growable:false);
  }

  Future<List<AuthenticatedPortfolioValuedPosition>> loadValuedPositions({required MarketRepository marketRepository}) async {
    final holdings=await loadPositions(); final valued=<AuthenticatedPortfolioValuedPosition>[];
    for(final holding in holdings){final quote=await marketRepository.getQuote(holding.symbol); _validateMarketQuote(holding:holding,quote:quote); valued.add(AuthenticatedPortfolioValuedPosition(holding:holding,quote:quote));}
    return List.unmodifiable(valued);
  }

  void _validateMarketQuote({required AuthenticatedPortfolioPosition holding, required MarketQuote quote}) {
    final expected=holding.symbol.trim().toUpperCase(), actual=quote.symbol.trim().toUpperCase();
    if(expected.isEmpty||actual!=expected) throw StateError('La cotización no corresponde a la posición autenticada solicitada.');
    if(!quote.currentPrice.isFinite||quote.currentPrice<=0) throw StateError('Cotización actual inválida para la cartera autenticada.');
    final provider=quote.sourceProvider?.trim(), retrieved=quote.retrievedAt; if(provider==null||provider.isEmpty||retrieved==null) throw StateError('La valoración autenticada requiere provenance de mercado completa.');
    if(retrieved.isBefore(quote.updatedAt)) throw StateError('La recuperación de mercado no puede preceder a la observación.');
    final he=holding.exchange?.trim().toUpperCase(), qe=quote.exchange?.trim().toUpperCase(); if(he!=null&&he.isNotEmpty&&(qe==null||qe.isEmpty||qe!=he)) throw StateError('La cotización pertenece a un listing distinto de la posición autenticada.');
  }

  Future<AuthenticatedPortfolioHistory> loadHistory({String portfolioId='primary',DateTime? asOf,int limit=100}) async {
    final id=portfolioId.trim(); if(id.isEmpty||id.length>128) throw ArgumentError.value(portfolioId,'portfolioId','Portfolio id no válido.'); if(limit<1||limit>500) throw ArgumentError.value(limit,'limit','Limit debe estar entre 1 y 500.');
    final cutoff=(asOf??DateTime.now()).toUtc(); final uri=Uri.parse('$_baseUrl/api/v1/user/portfolio/history').replace(queryParameters:{'portfolioId':id,'asOf':cutoff.toIso8601String(),'limit':'$limit'});
    final token=_currentToken(); final response=await _client.get(uri,headers:_headersFor(token)); await _rejectInvalidSession(response,token); _requireCurrentToken(token); final data=_decodeObject(response)['data']; if(data is! Map<String,dynamic>) throw const FormatException('Respuesta de historial sin data válida.'); return AuthenticatedPortfolioHistory.fromJson(data);
  }

  Future<AuthenticatedPortfolioPosition> upsertPosition({required String symbol,String? exchange,required double quantity,double? averagePurchasePrice}) async {
    final ns=symbol.trim().toUpperCase(), ne=exchange?.trim().toUpperCase(); if(ns.isEmpty||ns.length>32) throw ArgumentError.value(symbol,'symbol','Símbolo no válido.'); if(!quantity.isFinite||quantity<=0||quantity>_maxEconomicValue) throw ArgumentError.value(quantity,'quantity','Cantidad no válida.'); if(averagePurchasePrice!=null&&(!averagePurchasePrice.isFinite||averagePurchasePrice<=0||averagePurchasePrice>_maxEconomicValue)) throw ArgumentError.value(averagePurchasePrice,'averagePurchasePrice','Precio medio no válido.');
    final body=<String,dynamic>{'symbol':ns,'exchange':ne==null||ne.isEmpty?null:ne,'quantity':quantity,'averagePurchasePrice':?averagePurchasePrice}; final token=_currentToken(); final response=await _client.put(Uri.parse('$_baseUrl/api/v1/user/portfolio/positions'),headers:_headersFor(token,json:true),body:jsonEncode(body)); await _rejectInvalidSession(response,token); _requireCurrentToken(token); final data=_decodeObject(response)['data']; if(data is! Map<String,dynamic>) throw const FormatException('Respuesta de posición sin data válida.'); return AuthenticatedPortfolioPosition.fromJson(data);
  }

  Future<void> deletePosition(int positionId) async { if(positionId<=0) throw ArgumentError.value(positionId,'positionId','Id no válido.'); final token=_currentToken(); final response=await _client.delete(Uri.parse('$_baseUrl/api/v1/user/portfolio/positions/$positionId'),headers:_headersFor(token)); await _rejectInvalidSession(response,token); _requireCurrentToken(token); if(response.statusCode!=204) throw StateError(_errorMessage(response)); }

  void _requireCurrentToken(String requestToken) {
    final currentToken = _session.accessToken?.trim();
    if (!_session.isAuthenticated || currentToken != requestToken) {
      throw const AuthenticatedPortfolioAuthorityChangedException();
    }
  }

  Future<void> _rejectInvalidSession(http.Response response,String requestToken) async { if(response.statusCode!=401&&response.statusCode!=403) return; _lastRejectedStatusCode=response.statusCode; await _session.clearAfterRemoteInvalidationIfCurrent(requestToken); throw AuthSessionRejectedException(response.statusCode); }

  Map<String,dynamic> _decodeObject(http.Response response){if(response.statusCode<200||response.statusCode>=300) throw StateError(_errorMessage(response)); final decoded=jsonDecode(response.body); if(decoded is! Map<String,dynamic>) throw const FormatException('Respuesta ATHENA no válida.'); return decoded;}
  String _errorMessage(http.Response response){try{final decoded=jsonDecode(response.body);if(decoded is Map<String,dynamic>&&decoded['detail'] is String)return decoded['detail'] as String;}catch(_){} return 'La cartera autenticada no pudo completar la operación.';}
  void dispose(){if(_ownsClient)_client.close();}
}
