/// Traceable RSS headlines selected for a company, not verified issuer facts.
class CompanyNewsEvidenceItem {
  final String id;
  final String summary;
  final String publisher;
  final String provider;
  final String sourceUrl;
  final DateTime publishedAt;
  final DateTime availableAt;

  const CompanyNewsEvidenceItem({
    required this.id, required this.summary, required this.publisher,
    required this.provider, required this.sourceUrl,
    required this.publishedAt, required this.availableAt,
  });
}

class CompanyNewsEvidence {
  final String symbol;
  final String companyName;
  final String provider;
  final DateTime retrievedAt;
  final int rejectedCount;
  final List<CompanyNewsEvidenceItem> items;

  const CompanyNewsEvidence({
    required this.symbol, required this.companyName, required this.provider,
    required this.retrievedAt, required this.rejectedCount, required this.items,
  });

  static String _text(Object? value, String name) {
    if (value is! String || value.trim().isEmpty) {
      throw FormatException('$name es obligatorio.');
    }
    return value.trim();
  }

  static DateTime _date(Object? value, String name) {
    final raw = _text(value, name);
    if (!RegExp(r'(Z|[+-][0-9]{2}:[0-9]{2})$').hasMatch(raw)) {
      throw FormatException('$name requiere zona horaria.');
    }
    final date = DateTime.tryParse(raw);
    if (date == null) throw FormatException('$name inválida.');
    return date.toUtc();
  }

  static String _https(Object? value) {
    final url = _text(value, 'sourceRef');
    final uri = Uri.tryParse(url);
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty ||
        uri.userInfo.isNotEmpty || url.contains('\\')) {
      throw const FormatException('La fuente debe ser HTTPS sin credenciales.');
    }
    return url;
  }

  factory CompanyNewsEvidence.fromMap(
    Map<String, dynamic> root, {
    required String requestedSymbol,
    required String requestedCompanyName,
  }) {
    final raw = root['data'];
    if (raw is! Map) throw const FormatException('Falta data.');
    final data = Map<String, dynamic>.from(raw);
    final symbol = _text(data['symbol'], 'symbol');
    final companyName = _text(data['companyName'], 'companyName');
    if (symbol != requestedSymbol.trim().toUpperCase() ||
        companyName != requestedCompanyName.trim()) {
      throw const FormatException('Identidad de la consulta contradictoria.');
    }
    if (data['readOnly'] != true ||
        data['mode'] != 'research_evidence_only' ||
        data['advisoryStatus'] != 'no_advice' ||
        data['productionEligible'] != false ||
        data['licenseVerified'] != false ||
        data['modelExecutionVerified'] != false ||
        data['persisted'] != false ||
        data['issuerIdentityIndependentlyVerified'] != false ||
        data['independentCorroborationClaimed'] != false ||
        data['productionTruthClaimed'] != false ||
        data['headlineMentionRequired'] != true ||
        data['recommendationInfluence'] != false ||
        data['automaticScoring'] != false ||
        data['automaticTrading'] != false) {
      throw const FormatException('Política de evidencia empresarial insegura.');
    }
    final provider = _text(data['sourceProvider'], 'sourceProvider');
    if (provider != 'google_news_rss') {
      throw const FormatException('Proveedor de noticias inesperado.');
    }
    final retrievedAt = _date(data['retrievedAt'], 'retrievedAt');
    if (retrievedAt.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Recuperación futura.');
    }
    final asOfRaw = data['asOf'];
    final asOf = asOfRaw == null ? null : _date(asOfRaw, 'asOf');
    if (asOf != null && asOf.isAfter(DateTime.now().toUtc())) {
      throw const FormatException('Corte PIT futuro.');
    }
    final entries = data['evidence'];
    if (entries is! List) throw const FormatException('Evidencias inválidas.');
    final accepted = data['acceptedCount'];
    final rejected = data['rejectedCount'];
    if (accepted is! int || rejected is! int || accepted < 0 ||
        rejected < 0 || accepted != entries.length ||
        data['provenanceComplete'] != (accepted > 0) ||
        data['status'] != (accepted > 0
            ? 'news_evidence_ready' : 'news_evidence_unavailable')) {
      throw const FormatException('Inventario de noticias incoherente.');
    }
    final seen = <String>{};
    final items = <CompanyNewsEvidenceItem>[];
    for (final entry in entries) {
      if (entry is! Map) throw const FormatException('Evidencia inválida.');
      final item = Map<String, dynamic>.from(entry);
      final id = _text(item['evidenceId'], 'evidenceId');
      final url = _https(item['sourceRef']);
      final published = _date(item['publishedAt'], 'publishedAt');
      final available = _date(item['availableAt'], 'availableAt');
      if (item['category'] != 'news' || item['source'] != 'news' ||
          !{'routine', 'material', 'critical'}.contains(item['urgency']) ||
          item['provider'] != provider || !id.startsWith('news:') ||
          published.isAfter(available) || available.isAfter(retrievedAt) ||
          (asOf != null && available.isAfter(asOf)) ||
          !seen.add(url.toLowerCase())) {
        throw const FormatException('Evidencia PIT o procedencia inválida.');
      }
      items.add(CompanyNewsEvidenceItem(
        id: id, summary: _text(item['summary'], 'summary'),
        publisher: _text(item['publisher'], 'publisher'),
        provider: provider, sourceUrl: url,
        publishedAt: published, availableAt: available,
      ));
    }
    return CompanyNewsEvidence(
      symbol: symbol, companyName: companyName, provider: provider,
      retrievedAt: retrievedAt, rejectedCount: rejected, items: items,
    );
  }
}
