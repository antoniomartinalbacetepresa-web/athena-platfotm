class VerifiedNewsItem {
  final String title;
  final String publisher;
  final String? publisherUrl;
  final String articleUrl;
  final DateTime publishedAt;
  final DateTime retrievedAt;
  final String sourceProvider;

  const VerifiedNewsItem({
    required this.title,
    required this.publisher,
    required this.publisherUrl,
    required this.articleUrl,
    required this.publishedAt,
    required this.retrievedAt,
    required this.sourceProvider,
  });

  factory VerifiedNewsItem.fromMap(Map<String, dynamic> map) {
    final title = _requiredString(map['title'], 'title');
    final publisher = _requiredString(map['publisher'], 'publisher');
    final articleUrl = _requiredHttpsUrl(map['articleUrl'], 'articleUrl');
    final publisherUrl = _optionalHttpsUrl(map['publisherUrl'], 'publisherUrl');
    final publishedAt = _requiredUtcDateTime(map['publishedAt'], 'publishedAt');
    final retrievedAt = _requiredUtcDateTime(map['retrievedAt'], 'retrievedAt');
    final sourceProvider = _requiredString(map['sourceProvider'], 'sourceProvider');

    if (publishedAt.isAfter(retrievedAt)) {
      throw const FormatException(
        'publishedAt no puede ser posterior a retrievedAt.',
      );
    }

    return VerifiedNewsItem(
      title: title,
      publisher: publisher,
      publisherUrl: publisherUrl,
      articleUrl: articleUrl,
      publishedAt: publishedAt,
      retrievedAt: retrievedAt,
      sourceProvider: sourceProvider,
    );
  }
}

class VerifiedNewsFeed {
  final String query;
  final String sourceProvider;
  final DateTime retrievedAt;
  final List<VerifiedNewsItem> items;

  const VerifiedNewsFeed({
    required this.query,
    required this.sourceProvider,
    required this.retrievedAt,
    required this.items,
  });

  factory VerifiedNewsFeed.fromMap(Map<String, dynamic> map) {
    if (map['status'] != 'news_feed_ready') {
      throw const FormatException('El feed de noticias no está listo.');
    }
    if (map['advisoryStatus'] != 'no_advice' ||
        map['productionEligible'] != false) {
      throw const FormatException('Contrato de noticias inseguro.');
    }

    final policy = map['policy'];
    if (policy is! Map ||
        policy['athenaRecommendationInfluence'] != false ||
        policy['automaticScoring'] != false ||
        policy['automaticTrading'] != false) {
      throw const FormatException('Política de noticias insegura.');
    }

    final query = _requiredString(map['query'], 'query');
    final sourceProvider = _requiredString(
      map['sourceProvider'],
      'sourceProvider',
    );
    final retrievedAt = _requiredUtcDateTime(map['retrievedAt'], 'retrievedAt');
    final rawItems = map['items'];
    if (rawItems is! List) {
      throw const FormatException('items debe ser una lista.');
    }

    final items = rawItems.map((raw) {
      if (raw is! Map) {
        throw const FormatException('Artículo de noticias inválido.');
      }
      final item = VerifiedNewsItem.fromMap(Map<String, dynamic>.from(raw));
      if (item.sourceProvider != sourceProvider ||
          item.retrievedAt != retrievedAt) {
        throw const FormatException(
          'La provenance del artículo no coincide con la del feed.',
        );
      }
      return item;
    }).toList(growable: false);

    final count = map['count'];
    if (count is! int || count < 0 || count != items.length) {
      throw const FormatException('count no coincide con los artículos.');
    }

    return VerifiedNewsFeed(
      query: query,
      sourceProvider: sourceProvider,
      retrievedAt: retrievedAt,
      items: items,
    );
  }
}

String _requiredString(Object? value, String field) {
  if (value is! String || value.trim().isEmpty) {
    throw FormatException('$field es obligatorio.');
  }
  return value.trim();
}

String _requiredHttpsUrl(Object? value, String field) {
  final url = _requiredString(value, field);
  final uri = Uri.tryParse(url);
  if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
    throw FormatException('$field debe ser una URL HTTPS válida.');
  }
  return url;
}

String? _optionalHttpsUrl(Object? value, String field) {
  if (value == null) return null;
  return _requiredHttpsUrl(value, field);
}

DateTime _requiredUtcDateTime(Object? value, String field) {
  if (value is! String || value.trim().isEmpty) {
    throw FormatException('$field es obligatorio.');
  }
  final parsed = DateTime.tryParse(value);
  if (parsed == null || !parsed.isUtc) {
    throw FormatException('$field debe ser una fecha UTC válida.');
  }
  return parsed;
}
