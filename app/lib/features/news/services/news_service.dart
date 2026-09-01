import '../models/news_article.dart';

abstract interface class NewsService {
  Future<List<NewsArticle>> getLatestNews();

  Future<List<NewsArticle>> getNewsForSymbol(
    String symbol,
  );
}