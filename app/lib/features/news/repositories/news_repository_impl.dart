import '../models/news_article.dart';
import '../services/news_service.dart';
import 'news_repository.dart';

class NewsRepositoryImpl implements NewsRepository {
  final NewsService service;

  const NewsRepositoryImpl({
    required this.service,
  });

  @override
  Future<List<NewsArticle>> getLatestNews() {
    return service.getLatestNews();
  }

  @override
  Future<List<NewsArticle>> getNewsForSymbol(
    String symbol,
  ) {
    return service.getNewsForSymbol(symbol);
  }
}