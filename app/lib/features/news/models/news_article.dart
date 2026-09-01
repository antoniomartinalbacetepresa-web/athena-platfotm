class NewsArticle {
  final String id;
  final String title;
  final String source;
  final DateTime publishedAt;
  final String url;
  final String? summary;
  final String? imageUrl;
  final String? symbol;
  final String category;
  final double relevance;

  const NewsArticle({
    required this.id,
    required this.title,
    required this.source,
    required this.publishedAt,
    required this.url,
    this.summary,
    this.imageUrl,
    this.symbol,
    required this.category,
    required this.relevance,
  });

  bool get hasSummary =>
      summary != null && summary!.trim().isNotEmpty;

  bool get hasImage =>
      imageUrl != null && imageUrl!.trim().isNotEmpty;

  bool get hasSymbol =>
      symbol != null && symbol!.trim().isNotEmpty;

  NewsArticle copyWith({
    String? id,
    String? title,
    String? source,
    DateTime? publishedAt,
    String? url,
    String? summary,
    String? imageUrl,
    String? symbol,
    String? category,
    double? relevance,
  }) {
    return NewsArticle(
      id: id ?? this.id,
      title: title ?? this.title,
      source: source ?? this.source,
      publishedAt: publishedAt ?? this.publishedAt,
      url: url ?? this.url,
      summary: summary ?? this.summary,
      imageUrl: imageUrl ?? this.imageUrl,
      symbol: symbol ?? this.symbol,
      category: category ?? this.category,
      relevance: relevance ?? this.relevance,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'title': title,
      'source': source,
      'publishedAt': publishedAt.toIso8601String(),
      'url': url,
      'summary': summary,
      'imageUrl': imageUrl,
      'symbol': symbol,
      'category': category,
      'relevance': relevance,
    };
  }

  factory NewsArticle.fromMap(Map<String, dynamic> map) {
    return NewsArticle(
      id: map['id'] as String,
      title: map['title'] as String,
      source: map['source'] as String,
      publishedAt: DateTime.parse(
        map['publishedAt'] as String,
      ),
      url: map['url'] as String,
      summary: map['summary'] as String?,
      imageUrl: map['imageUrl'] as String?,
      symbol: map['symbol'] as String?,
      category: map['category'] as String,
      relevance: (map['relevance'] as num).toDouble(),
    );
  }
}