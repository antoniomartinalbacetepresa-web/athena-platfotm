import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/portfolio_position.dart';

class AthenaBackendPortfolioValuationEvidence {
  final DateTime asOf;
  final String baseCurrency;
  final int positionCount;
  final double investedPositionsValueInBaseCurrency;
  final String valuationFingerprint;
  final DateTime persistedAt;
  final String recordFingerprint;

  const AthenaBackendPortfolioValuationEvidence({
    required this.asOf,
    required this.baseCurrency,
    required this.positionCount,
    required this.investedPositionsValueInBaseCurrency,
    required this.valuationFingerprint,
    required this.persistedAt,
    required this.recordFingerprint,
  });
}

class AthenaBackendPortfolioValuationDataSource {
  final String baseUrl;
  final http.Client client;

  AthenaBackendPortfolioValuationDataSource({
    required this.baseUrl,
    http.Client? client,
  }) : client = client ?? http.Client();

  Future<AthenaBackendPortfolioValuationEvidence> buildAndSeal({
    required List<PortfolioPosition> positions,
    required String baseCurrency,
    required DateTime asOf,
  }) async {
    final currency = baseCurrency.trim().toUpperCase();
    if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
      throw ArgumentError.value(
        baseCurrency,
        'baseCurrency',
        'Debe ser una moneda ISO de tres letras.',
      );
    }
    final cutoff = asOf.toUtc();
    final requestedIds = <int>{};
    final payloadPositions = <Map<String, Object?>>[];

    for (final position in positions) {
      final instrumentId = position.databaseInstrumentId;
      if (!position.hasVerifiedCanonicalIdentity ||
          instrumentId == null ||
          instrumentId <= 0) {
        throw StateError(
          'La valoración backend requiere identidad canónica verificable.',
        );
      }
      if (!position.hasVerifiedPositionProvenance) {
        throw StateError(
          'La valoración backend requiere provenance verificable de la posición.',
        );
      }
      if (!position.shares.isFinite || position.shares <= 0) {
        throw StateError('La cantidad de la posición debe ser positiva y finita.');
      }
      if (!requestedIds.add(instrumentId)) {
        throw StateError(
          'La valoración backend no admite instrumentos canónicos duplicados.',
        );
      }
      final marketProvider = position.currentPriceSourceProvider?.trim();
      if (marketProvider == null || marketProvider.isEmpty) {
        throw StateError(
          'La posición no identifica el proveedor de mercado verificable.',
        );
      }
      final observedAt = position.positionObservedAt!.toUtc();
      final retrievedAt = position.positionRetrievedAt!.toUtc();
      if (retrievedAt.isAfter(cutoff)) {
        throw StateError(
          'La declaración de posición fue conocida después del corte PIT.',
        );
      }

      payloadPositions.add({
        'instrumentId': instrumentId,
        'quantity': position.shares,
        'positionSourceProvider': position.positionSourceProvider!.trim(),
        'positionObservedAt': observedAt.toIso8601String(),
        'positionRetrievedAt': retrievedAt.toIso8601String(),
        'marketSourceProvider': marketProvider,
      });
    }

    final uri = Uri.parse('$baseUrl/api/v1/portfolio/valuation-evidence');
    final response = await client.post(
      uri,
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({
        'baseCurrency': currency,
        'asOf': cutoff.toIso8601String(),
        'positions': payloadPositions,
      }),
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'El backend de ATHENA TYCHE respondió con código HTTP '
        '${response.statusCode} al construir la valoración PIT.',
      );
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException(
        'La respuesta de valoración no es un objeto JSON válido.',
      );
    }
    final rawData = decoded['data'];
    final rawPersistence = decoded['persistence'];
    if (rawData is! Map || rawPersistence is! Map) {
      throw const FormatException(
        'La respuesta de valoración no contiene evidencia sellada válida.',
      );
    }
    final data = Map<String, dynamic>.from(rawData);
    final persistence = Map<String, dynamic>.from(rawPersistence);

    if (data['artifactVersion'] != 'athena-portfolio-valuation-evidence-v1' ||
        data['status'] !=
            'portfolio_valuation_evidence_verified_non_advisory' ||
        data['portfolioValuationEvidenceReady'] != true ||
        data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['automaticTrading'] != false ||
        data['cashIncluded'] != false ||
        data['liabilitiesIncluded'] != false ||
        data['valuationScope'] !=
            'invested_long_positions_only_cash_liabilities_unsettled_excluded') {
      throw const FormatException(
        'La valoración backend violó el contrato no advisory o de alcance.',
      );
    }

    final returnedCurrency = data['baseCurrency']?.toString().toUpperCase();
    if (returnedCurrency != currency) {
      throw const FormatException(
        'La valoración backend cambió la moneda base solicitada.',
      );
    }
    final returnedAsOf = DateTime.tryParse(data['asOf']?.toString() ?? '')?.toUtc();
    if (returnedAsOf == null || returnedAsOf != cutoff) {
      throw const FormatException(
        'La valoración backend cambió el corte point-in-time solicitado.',
      );
    }

    final rawCount = data['positionCount'];
    if (rawCount is! int || rawCount != positions.length) {
      throw const FormatException(
        'La valoración backend devolvió un número de posiciones inconsistente.',
      );
    }
    final returnedPositions = data['positions'];
    if (returnedPositions is! List || returnedPositions.length != rawCount) {
      throw const FormatException(
        'La valoración backend devolvió posiciones inconsistentes.',
      );
    }
    final returnedIds = <int>{};
    for (final rawPosition in returnedPositions) {
      if (rawPosition is! Map) {
        throw const FormatException(
          'La valoración backend contiene una posición inválida.',
        );
      }
      final id = rawPosition['instrumentId'];
      if (id is! int || id <= 0 || !returnedIds.add(id)) {
        throw const FormatException(
          'La valoración backend contiene identidad duplicada o inválida.',
        );
      }
    }
    if (returnedIds.length != requestedIds.length ||
        !returnedIds.containsAll(requestedIds)) {
      throw const FormatException(
        'La valoración backend no corresponde a los instrumentos solicitados.',
      );
    }

    final rawTotal = data['investedPositionsValueInBaseCurrency'];
    if (rawTotal is! num || !rawTotal.toDouble().isFinite || rawTotal < 0) {
      throw const FormatException(
        'La valoración backend devolvió un agregado no finito o negativo.',
      );
    }
    final valuationFingerprint =
        data['portfolioValuationEvidenceFingerprint']?.toString() ?? '';
    if (!_isSha256(valuationFingerprint)) {
      throw const FormatException(
        'La valoración backend carece de fingerprint SHA-256 válido.',
      );
    }
    if (persistence['sealed'] != true) {
      throw const FormatException(
        'La valoración backend no acredita persistencia sellada.',
      );
    }
    final persistedAt =
        DateTime.tryParse(persistence['persistedAt']?.toString() ?? '')?.toUtc();
    final recordFingerprint = persistence['recordFingerprint']?.toString() ?? '';
    if (persistedAt == null || !_isSha256(recordFingerprint)) {
      throw const FormatException(
        'La persistencia de valoración carece de provenance válida.',
      );
    }

    return AthenaBackendPortfolioValuationEvidence(
      asOf: returnedAsOf,
      baseCurrency: currency,
      positionCount: rawCount,
      investedPositionsValueInBaseCurrency: rawTotal.toDouble(),
      valuationFingerprint: valuationFingerprint,
      persistedAt: persistedAt,
      recordFingerprint: recordFingerprint,
    );
  }

  static bool _isSha256(String value) =>
      RegExp(r'^[0-9a-f]{64}$').hasMatch(value.toLowerCase());

  void dispose() {
    client.close();
  }
}
