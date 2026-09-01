import 'dart:convert';

import 'package:http/http.dart' as http;

import 'financial_data.dart';
import 'financial_data_provider.dart';

/// Proveedor de datos financieros basado en Alpha Vantage.
///
/// Se centra en datos fundamentales de empresa.
/// La clave API se recibe por inyección y no se almacena
/// en el código fuente de ATHENA TYCHE.
class AlphaVantageFinancialDataProvider
    implements FinancialDataProvider {
  static const String _providerId = 'alpha_vantage';

  final String apiKey;
  final http.Client client;
  final String baseUrl;

  AlphaVantageFinancialDataProvider({
    required this.apiKey,
    http.Client? client,
    this.baseUrl = 'https://www.alphavantage.co/query',
  }) : client = client ?? http.Client();

  @override
  String get providerId => _providerId;

  @override
  Future<FinancialData?> getFinancialData({
    required String symbol,
  }) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty || apiKey.trim().isEmpty) {
      return null;
    }

    final overview = await _getEndpoint(
      function: 'OVERVIEW',
      symbol: normalizedSymbol,
    );

    if (overview == null || overview.isEmpty) {
      return null;
    }

    final incomeStatement = await _getEndpoint(
      function: 'INCOME_STATEMENT',
      symbol: normalizedSymbol,
    );

    final balanceSheet = await _getEndpoint(
      function: 'BALANCE_SHEET',
      symbol: normalizedSymbol,
    );

    final cashFlow = await _getEndpoint(
      function: 'CASH_FLOW',
      symbol: normalizedSymbol,
    );

    final income =
        _firstReport(incomeStatement?['annualReports']);

    final balance =
        _firstReport(balanceSheet?['annualReports']);

    final cash =
        _firstReport(cashFlow?['annualReports']);

    return FinancialData(
      symbol: normalizedSymbol,
      companyName: _stringValue(overview['Name']),
      currency: _stringValue(overview['Currency']),
      periodEnd: _parseDate(
        income?['fiscalDateEnding'],
      ),
      periodType: 'annual',
      revenue: _number(
        income?['totalRevenue'],
      ),
      ebitda: _number(
        income?['ebitda'] ?? overview['EBITDA'],
      ),
      ebit: _number(
        income?['ebit'],
      ),
      netIncome: _number(
        income?['netIncome'],
      ),
      eps: _number(
        overview['EPS'],
      ),
      cash: _number(
        balance?['cashAndCashEquivalentsAtCarryingValue'],
      ),
      totalDebt: _number(
        balance?['shortLongTermDebtTotal'],
      ),
      grossMargin: _number(
        overview['ProfitMargin'],
      ),
      operatingMargin: _number(
        overview['OperatingMarginTTM'],
      ),
      netMargin: _number(
        overview['ProfitMargin'],
      ),
      operatingCashFlow: _number(
        cash?['operatingCashflow'],
      ),
      freeCashFlow: _calculateFreeCashFlow(
        cash,
      ),
      providerId: providerId,
    );
  }

  Future<Map<String, dynamic>?> _getEndpoint({
    required String function,
    required String symbol,
  }) async {
    final uri = Uri.parse(baseUrl).replace(
      queryParameters: {
        'function': function,
        'symbol': symbol,
        'apikey': apiKey,
      },
    );

    final response = await client.get(uri);

    if (response.statusCode != 200) {
      throw Exception(
        'Alpha Vantage respondió con HTTP '
        '${response.statusCode}.',
      );
    }

    final decoded = jsonDecode(response.body);

    if (decoded is! Map) {
      return null;
    }

    final data = Map<String, dynamic>.from(decoded);

    if (data.containsKey('Error Message')) {
      throw Exception(
        'Alpha Vantage devolvió un error: '
        '${data['Error Message']}',
      );
    }

    if (data.containsKey('Information')) {
      throw Exception(
        'Alpha Vantage informó: ${data['Information']}',
      );
    }

    return data;
  }

  Map<String, dynamic>? _firstReport(dynamic reports) {
    if (reports is! List || reports.isEmpty) {
      return null;
    }

    final first = reports.first;

    if (first is Map) {
      return Map<String, dynamic>.from(first);
    }

    return null;
  }

  double? _number(dynamic value) {
    if (value == null) {
      return null;
    }

    if (value is num) {
      return value.toDouble();
    }

    final text = value.toString().trim();

    if (text.isEmpty || text == 'None' || text == 'null') {
      return null;
    }

    return double.tryParse(text);
  }

  String? _stringValue(dynamic value) {
    if (value == null) {
      return null;
    }

    final text = value.toString().trim();

    return text.isEmpty ? null : text;
  }

  DateTime? _parseDate(dynamic value) {
    final text = _stringValue(value);

    if (text == null) {
      return null;
    }

    return DateTime.tryParse(text);
  }

  double? _calculateFreeCashFlow(
    Map<String, dynamic>? cashFlow,
  ) {
    if (cashFlow == null) {
      return null;
    }

    final operatingCashFlow =
        _number(cashFlow['operatingCashflow']);

    final capitalExpenditures =
        _number(cashFlow['capitalExpenditures']);

    if (operatingCashFlow == null ||
        capitalExpenditures == null) {
      return null;
    }

    return operatingCashFlow - capitalExpenditures.abs();
  }

  void dispose() {
    client.close();
  }
}