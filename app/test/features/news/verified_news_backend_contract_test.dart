import 'package:app/features/news/models/verified_news_feed.dart';
import 'package:app/features/news/services/athena_backend_news_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  Map<String, dynamic> validPayload() => {
        'status': 'news_feed_ready',
        'query': 'stock market earnings economy',
        'count': 1,
        'sourceProvider': 'google_news_rss',
        'retrievedAt': '2026-09-04T10:00:00Z',
        'items': [
          {
            'title': 'Verified market headline',
            'publisher': 'Example Publisher',
            'publisherUrl': 'https://example.com',
            'articleUrl': 'https://news.google.com/articles/example',
            'publishedAt': '2026-09-04T09:30:00Z',
            'retrievedAt': '2026-09-04T10:00:00Z',
            'sourceProvider': 'google_news_rss',
          },
        ],
        'policy': {
          'athenaRecommendationInfluence': false,
          'automaticScoring': false,
          'automaticTrading': false,
        },
        'advisoryStatus': 'no_advice',
        'productionEligible': false,
      };

  test('verified feed preserves article provenance and safety policy', () {
    final feed = VerifiedNewsFeed.fromMap(validPayload());

    expect(feed.sourceProvider, 'google_news_rss');
    expect(feed.retrievedAt.isUtc, isTrue);
    expect(feed.items, hasLength(1));
    expect(feed.items.single.publisher, 'Example Publisher');
    expect(feed.items.single.articleUrl, startsWith('https://'));
    expect(feed.items.single.publishedAt.isBefore(feed.retrievedAt), isTrue);
  });

  test('verified feed rejects recommendation influence', () {
    final payload = validPayload();
    (payload['policy'] as Map<String, dynamic>)[
        'athenaRecommendationInfluence'] = true;

    expect(
      () => VerifiedNewsFeed.fromMap(payload),
      throwsFormatException,
    );
  });

  test('verified feed rejects non HTTPS article URLs', () {
    final payload = validPayload();
    ((payload['items'] as List).single as Map<String, dynamic>)[
        'articleUrl'] = 'http://example.com/article';

    expect(
      () => VerifiedNewsFeed.fromMap(payload),
      throwsFormatException,
    );
  });

  test('verified feed rejects future publication relative to retrieval', () {
    final payload = validPayload();
    ((payload['items'] as List).single as Map<String, dynamic>)[
        'publishedAt'] = '2026-09-04T10:30:00Z';

    expect(
      () => VerifiedNewsFeed.fromMap(payload),
      throwsFormatException,
    );
  });

  test('backend service requests ATHENA endpoint and validates contract', () async {
    late Uri requested;
    final client = MockClient((request) async {
      requested = request.url;
      return http.Response(
        '''{"status":"news_feed_ready","query":"stock market earnings economy","count":0,"sourceProvider":"google_news_rss","retrievedAt":"2026-09-04T10:00:00Z","items":[],"policy":{"athenaRecommendationInfluence":false,"automaticScoring":false,"automaticTrading":false},"advisoryStatus":"no_advice","productionEligible":false}''',
        200,
      );
    });
    final service = AthenaBackendNewsService(
      baseUrl: 'http://127.0.0.1:8000',
      client: client,
    );

    final feed = await service.getFeed(limit: 8, language: 'en', country: 'US');

    expect(requested.path, '/api/v1/news/feed');
    expect(requested.queryParameters['limit'], '8');
    expect(requested.queryParameters['language'], 'en');
    expect(requested.queryParameters['country'], 'US');
    expect(feed.items, isEmpty);
  });

  test('backend service rejects unsafe backend payload', () async {
    final client = MockClient((request) async {
      return http.Response(
        '''{"status":"news_feed_ready","query":"x","count":0,"sourceProvider":"google_news_rss","retrievedAt":"2026-09-04T10:00:00Z","items":[],"policy":{"athenaRecommendationInfluence":true,"automaticScoring":false,"automaticTrading":false},"advisoryStatus":"no_advice","productionEligible":false}''',
        200,
      );
    });
    final service = AthenaBackendNewsService(
      baseUrl: 'http://127.0.0.1:8000',
      client: client,
    );

    expect(service.getFeed(), throwsFormatException);
  });
}
