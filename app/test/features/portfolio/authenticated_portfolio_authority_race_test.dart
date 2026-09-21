import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _TokenStore implements AuthTokenStore {
  @override
  Future<void> deleteAccessToken() async {}

  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<void> writeAccessToken(String token) async {}
}

class _MarketRepository implements MarketRepository {
  @override
  Future<MarketQuote> getQuote(String symbol) async => MarketQuote(
        symbol: symbol,
        companyName: symbol,
        currentPrice: symbol == 'MSFT' ? 500 : 200,
        change: 1,
        changePercentage: 0.5,
        currency: 'USD',
        exchange: 'NASDAQ',
        updatedAt: DateTime.parse('2026-09-21T09:00:00Z'),
        sourceProvider: 'yahoo_finance',
        retrievedAt: DateTime.parse('2026-09-21T09:00:02Z'),
      );
}

AuthAccount _account(int id, String email) => AuthAccount(
      id: id,
      email: email,
      displayName: 'Owner $id',
      isActive: true,
      createdAt: DateTime.parse('2026-09-21T08:00:00Z'),
      updatedAt: DateTime.parse('2026-09-21T08:00:00Z'),
    );

http.Response _portfolio(String symbol, int id) => http.Response(
      jsonEncode({
        'data': {
          'positions': [
            {
              'id': id,
              'symbol': symbol,
              'exchange': 'NASDAQ',
              'quantity': 1.0,
              'averagePurchasePrice': 100.0,
              'createdAt': '2026-09-21T08:00:00Z',
              'updatedAt': '2026-09-21T08:00:00Z',
            }
          ]
        }
      }),
      200,
      headers: {'content-type': 'application/json'},
    );

void main() {
  test('late owner A load cannot repopulate Portfolio after owner B replaces authority',
      () async {
    final session = AuthSession.forTesting(_TokenStore());
    session.establish(
      accessToken: 'owner-a.jwt',
      account: _account(1, 'a@example.com'),
    );

    final ownerAResponse = Completer<http.Response>();
    final ownerARequested = Completer<void>();
    final ownerBRequested = Completer<void>();
    final service = AuthenticatedPortfolioService(
      baseUrl: 'https://athena.local',
      session: session,
      client: MockClient((request) async {
        final authorization = request.headers['Authorization'];
        if (authorization == 'Bearer owner-a.jwt') {
          if (!ownerARequested.isCompleted) ownerARequested.complete();
          return ownerAResponse.future;
        }
        expect(authorization, 'Bearer owner-b.jwt');
        if (!ownerBRequested.isCompleted) ownerBRequested.complete();
        return _portfolio('MSFT', 22);
      }),
    );
    final controller = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _MarketRepository(),
      session: session,
    );

    final oldLoad = controller.load();
    await ownerARequested.future;

    session.establish(
      accessToken: 'owner-b.jwt',
      account: _account(2, 'b@example.com'),
    );
    expect(controller.positions, isEmpty);
    await ownerBRequested.future;

    ownerAResponse.complete(_portfolio('AAPL', 11));
    await oldLoad;
    for (var i = 0; i < 5 && controller.isLoading; i += 1) {
      await Future<void>.delayed(Duration.zero);
    }

    expect(session.accessToken, 'owner-b.jwt');
    expect(session.account?.id, 2);
    expect(controller.positions, hasLength(1));
    expect(controller.positions.single.symbol, 'MSFT');
    expect(controller.positions.single.serverPositionId, 22);
    expect(controller.positions.any((position) => position.symbol == 'AAPL'), isFalse);

    controller.dispose();
    service.dispose();
  });
}
