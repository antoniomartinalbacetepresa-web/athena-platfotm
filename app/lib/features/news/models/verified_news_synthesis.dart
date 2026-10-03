class VerifiedNewsSynthesisItem {
  final String evidenceId;
  final String symbol;
  final String sourceRef;
  final String publisher;
  final String modelProvider;
  final String modelName;
  final String modelVersion;
  final String summary;
  final String importance;
  final String impactDirection;
  final double impactMagnitude;
  final double confidence;

  const VerifiedNewsSynthesisItem({
    required this.evidenceId,
    required this.symbol,
    required this.sourceRef,
    required this.publisher,
    required this.modelProvider,
    required this.modelName,
    required this.modelVersion,
    required this.summary,
    required this.importance,
    required this.impactDirection,
    required this.impactMagnitude,
    required this.confidence,
  });

  factory VerifiedNewsSynthesisItem.fromMap(Map<String, dynamic> map) {
    String text(String key) {
      final value = map[key];
      if (value is! String || value.trim().isEmpty) {
        throw FormatException('News synthesis: $key es obligatorio.');
      }
      return value.trim();
    }

    double unit(String key) {
      final value = map[key];
      if (value is bool || value is! num || !value.isFinite) {
        throw FormatException('News synthesis: $key debe ser numérico.');
      }
      final parsed = value.toDouble();
      if (parsed < 0 || parsed > 1) {
        throw FormatException('News synthesis: $key debe estar entre 0 y 1.');
      }
      return parsed;
    }

    final evidenceId = text('evidenceId');
    final sourceRef = text('sourceRef');
    final uri = Uri.tryParse(sourceRef);
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
      throw const FormatException('News synthesis: sourceRef debe ser HTTPS.');
    }
    final provider = text('evidenceProvider').toLowerCase();
    final modelProvider = text('modelProvider');
    final compactProviders = '$provider$modelProvider'
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9]'), '');
    if (compactProviders.contains('financialmodelingprep') ||
        compactProviders.contains('fmp')) {
      throw const FormatException('News synthesis: FMP está prohibido.');
    }
    final importance = text('importance').toLowerCase();
    if (!const {'low', 'medium', 'high', 'critical'}.contains(importance)) {
      throw const FormatException('News synthesis: importance inválida.');
    }
    final impact = text('impactDirection').toLowerCase();
    if (!const {'negative', 'neutral', 'positive', 'mixed', 'uncertain'}
        .contains(impact)) {
      throw const FormatException('News synthesis: impactDirection inválido.');
    }
    for (final key in const ['inputFingerprint', 'assessmentFingerprint']) {
      final fingerprint = text(key).toLowerCase();
      if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(fingerprint)) {
        throw FormatException('News synthesis: $key no es SHA-256 válido.');
      }
    }

    return VerifiedNewsSynthesisItem(
      evidenceId: evidenceId,
      symbol: text('symbol'),
      sourceRef: sourceRef,
      publisher: text('publisher'),
      modelProvider: modelProvider,
      modelName: text('modelName'),
      modelVersion: text('modelVersion'),
      summary: text('summary'),
      importance: importance,
      impactDirection: impact,
      impactMagnitude: unit('impactMagnitude'),
      confidence: unit('confidence'),
    );
  }
}

class VerifiedNewsSynthesis {
  final String cycleHash;
  final String radarHash;
  final String synthesisHash;
  final String asOf;
  final String minimumImportance;
  final int assessedCount;
  final int includedCount;
  final int excludedCount;
  final List<VerifiedNewsSynthesisItem> items;

  const VerifiedNewsSynthesis({
    required this.cycleHash,
    required this.radarHash,
    required this.synthesisHash,
    required this.asOf,
    required this.minimumImportance,
    required this.assessedCount,
    required this.includedCount,
    required this.excludedCount,
    required this.items,
  });

  factory VerifiedNewsSynthesis.fromMap(Map<String, dynamic> root) {
    final data = root['data'];
    if (data is! Map) {
      throw const FormatException('News synthesis: data ausente.');
    }
    final map = Map<String, dynamic>.from(data);
    if (map['cycleBindingVerified'] != true ||
        map['presentationOnly'] != true ||
        map['recommendationInfluence'] != false ||
        map['automaticScoring'] != false ||
        map['automaticTrading'] != false) {
      throw const FormatException('News synthesis: contrato de autoridad inválido.');
    }

    String sha(String key, Map<String, dynamic> source) {
      final value = source[key];
      if (value is! String || !RegExp(r'^[a-fA-F0-9]{64}$').hasMatch(value)) {
        throw FormatException('News synthesis: $key no es SHA-256 válido.');
      }
      return value.toLowerCase();
    }

    final synthesisRaw = map['synthesis'];
    final persistenceRaw = map['persistence'];
    if (synthesisRaw is! Map || persistenceRaw is! Map) {
      throw const FormatException('News synthesis: payload incompleto.');
    }
    final synthesis = Map<String, dynamic>.from(synthesisRaw);
    final persistence = Map<String, dynamic>.from(persistenceRaw);
    if (persistence['appendOnly'] != true ||
        persistence['packageIntegrityVerified'] != true ||
        synthesis['status'] != 'validated_external_model_output' ||
        synthesis['recommendationInfluence'] != false ||
        synthesis['automaticScoring'] != false ||
        synthesis['automaticTrading'] != false ||
        synthesis['modelExecutionVerified'] != false ||
        synthesis['productionTruthClaimed'] != false ||
        synthesis['independentCorroborationClaimed'] != false) {
      throw const FormatException('News synthesis: integridad/provenance no verificable.');
    }

    int count(String key) {
      final value = synthesis[key];
      if (value is! int || value < 0) {
        throw FormatException('News synthesis: $key inválido.');
      }
      return value;
    }

    final assessed = count('assessedCount');
    final included = count('includedCount');
    final excluded = count('excludedCount');
    if (assessed != included + excluded) {
      throw const FormatException('News synthesis: conteos inconsistentes.');
    }
    final rawItems = synthesis['items'];
    if (rawItems is! List || rawItems.length != included) {
      throw const FormatException('News synthesis: items inconsistentes.');
    }
    final items = rawItems
        .map((raw) {
          if (raw is! Map) {
            throw const FormatException('News synthesis: item inválido.');
          }
          return VerifiedNewsSynthesisItem.fromMap(Map<String, dynamic>.from(raw));
        })
        .toList(growable: false);
    if (items.map((item) => item.evidenceId).toSet().length != items.length) {
      throw const FormatException('News synthesis: evidenceId duplicado.');
    }

    final asOf = synthesis['asOf'];
    final threshold = synthesis['minimumImportance'];
    if (asOf is! String || DateTime.tryParse(asOf) == null || threshold is! String) {
      throw const FormatException('News synthesis: metadatos temporales inválidos.');
    }
    return VerifiedNewsSynthesis(
      cycleHash: sha('cycleHash', map),
      radarHash: sha('radarHash', map),
      synthesisHash: sha('synthesisHash', persistence),
      asOf: asOf,
      minimumImportance: threshold,
      assessedCount: assessed,
      includedCount: included,
      excludedCount: excluded,
      items: items,
    );
  }
}
