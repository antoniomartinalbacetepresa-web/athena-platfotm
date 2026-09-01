import '../models/news_article.dart';
import 'news_service.dart';

class MockNewsService implements NewsService {
  const MockNewsService();

  @override
  Future<List<NewsArticle>> getLatestNews() async {
    final now = DateTime.now();

    return [
      NewsArticle(
        id: 'mock-001',
        title: 'Los mercados analizan las últimas decisiones de política monetaria',
        source: 'ATHENA TYCHE Demo',
        publishedAt: now.subtract(
          const Duration(minutes: 15),
        ),
        url: 'https://example.com/news/mock-001',
        summary:
            'Los inversores siguen pendientes de la evolución de los tipos de interés y de los próximos datos macroeconómicos.',
        category: 'macro',
        relevance: 0.95,
      ),
      NewsArticle(
        id: 'mock-002',
        title: 'El sector tecnológico concentra la atención de los inversores',
        source: 'ATHENA TYCHE Demo',
        publishedAt: now.subtract(
          const Duration(minutes: 42),
        ),
        url: 'https://example.com/news/mock-002',
        summary:
            'Las expectativas de crecimiento y las valoraciones vuelven a situar al sector tecnológico en el centro del mercado.',
        category: 'technology',
        relevance: 0.88,
      ),
      NewsArticle(
        id: 'mock-003',
        title: 'Los mercados europeos mantienen un comportamiento mixto',
        source: 'ATHENA TYCHE Demo',
        publishedAt: now.subtract(
          const Duration(hours: 1, minutes: 10),
        ),
        url: 'https://example.com/news/mock-003',
        summary:
            'Los principales índices europeos muestran diferencias entre sectores mientras los inversores evalúan nuevos datos económicos.',
        category: 'markets',
        relevance: 0.81,
      ),
    ];
  }

  @override
  Future<List<NewsArticle>> getNewsForSymbol(
    String symbol,
  ) async {
    final normalizedSymbol = symbol.trim().toUpperCase();

    if (normalizedSymbol.isEmpty) {
      throw ArgumentError(
        'El símbolo no puede estar vacío.',
      );
    }

    final allNews = await getLatestNews();

    return allNews
        .where(
          (article) =>
              article.symbol?.toUpperCase() == normalizedSymbol,
        )
        .toList(growable: false);
  }
}