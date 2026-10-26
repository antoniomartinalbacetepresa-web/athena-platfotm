import 'dart:async';
import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/dashboard/presentation/widgets/authenticated_my_space_panel.dart';
import 'package:app/features/dashboard/presentation/widgets/my_space_panel.dart';
import 'package:app/features/market/models/market_quote.dart';
import 'package:app/features/market/repositories/market_repository.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_capital_controller.dart';
import 'package:app/features/portfolio/presentation/controllers/authenticated_portfolio_controller.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:app/features/profile/services/user_preferences_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _Market implements MarketRepository {
  _Market(this.currency);
  final String currency;

  @override
  Future<MarketQuote> getQuote(String symbol) async => MarketQuote(
        symbol: symbol,
        companyName: symbol,
        currentPrice: 200,
        change: 0,
        changePercentage: 0,
        currency: currency,
        exchange: 'NASDAQ',
        updatedAt: DateTime.utc(2026, 10, 25, 12),
        sourceProvider: 'yahoo_finance',
        retrievedAt: DateTime.utc(2026, 10, 25, 12, 1),
      );
}

AuthAccount _account(int id) => AuthAccount(
      id: id,
      email: 'owner-$id@example.invalid',
      isActive: true,
      createdAt: DateTime.utc(2026, 10, 25),
      updatedAt: DateTime.utc(2026, 10, 25),
    );

http.Response _holdings({bool empty = false}) => http.Response(
      jsonEncode({
        'data': {
          'positions': empty
              ? <Object>[]
              : [
                  {
                    'id': 1,
                    'symbol': 'AAPL',
                    'exchange': 'NASDAQ',
                    'quantity': 2,
                    'averagePurchasePrice': 160,
                    'createdAt': '2026-10-25T10:00:00Z',
                    'updatedAt': '2026-10-25T10:00:00Z',
                  }
                ],
        }
      }),
      200,
    );

http.Response _profile(String currency, {double capital = 1500}) =>
    http.Response(
      jsonEncode({
        'status': 'configured',
        'data': {
          'preferences': {
            'riskTolerance': 'balanced',
            'investmentHorizonYears': 10,
            'objective': 'balanced_growth',
            'baseCurrency': currency,
            'availableCapital': capital,
          },
        },
      }),
      200,
    );

void main() {
  final session = AuthSession.instance;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    session.clear();
    session.establish(accessToken: 'owner-a', account: _account(1));
  });
  tearDown(() => session.clear());

  testWidgets('Dashboard uses server owner holdings, never sums USD as EUR',
      (tester) async {
    final service = AuthenticatedPortfolioService(
      session: session,
      client: MockClient((_) async => _holdings()),
    );
    final preferences = UserPreferencesService(
      session: session,
      client: MockClient((_) async => _profile('EUR')),
    );
    final holdings = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _Market('USD'),
    );
    final capital = AuthenticatedPortfolioCapitalController(
      preferencesService: preferences,
    );
    await holdings.load();
    await capital.load();

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AuthenticatedMySpacePanel(
          portfolioController: holdings,
          capitalController: capital,
        ),
      ),
    ));
    expect(find.text('1'), findsOneWidget);
    expect(find.text('1500.00 EUR'), findsOneWidget);
    expect(find.text('400.00 EUR'), findsNothing);
    expect(find.text('80.00 EUR'), findsNothing);
    expect(find.text('No disponible'), findsNWidgets(2));
    expect(find.textContaining('no ejecuta órdenes'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    holdings.dispose();
    capital.dispose();
    service.dispose();
    preferences.dispose();
  });

  testWidgets('same-token owner replacement clears old Dashboard values immediately',
      (tester) async {
    final replacementHoldings = Completer<http.Response>();
    final replacementProfile = Completer<http.Response>();
    final service = AuthenticatedPortfolioService(
      session: session,
      client: MockClient((request) {
        if (session.account?.id == 2) return replacementHoldings.future;
        return Future.value(_holdings());
      }),
    );
    final preferences = UserPreferencesService(
      session: session,
      client: MockClient((request) {
        if (session.account?.id == 2) return replacementProfile.future;
        return Future.value(_profile('EUR'));
      }),
    );
    final holdings = AuthenticatedPortfolioController(
      portfolioService: service,
      marketRepository: _Market('EUR'),
    );
    final capital = AuthenticatedPortfolioCapitalController(
      preferencesService: preferences,
    );
    await holdings.load();
    await capital.load();

    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AuthenticatedMySpacePanel(
          portfolioController: holdings,
          capitalController: capital,
        ),
      ),
    ));
    expect(find.text('400.00 EUR'), findsOneWidget);
    expect(find.text('1500.00 EUR'), findsOneWidget);

    session.establish(accessToken: 'owner-a', account: _account(2));
    await tester.pump();
    expect(find.text('400.00 EUR'), findsNothing);
    expect(find.text('1500.00 EUR'), findsNothing);
    expect(find.byKey(const Key('dashboard-owner-loading')), findsOneWidget);

    replacementHoldings.complete(_holdings(empty: true));
    replacementProfile.complete(_profile('EUR', capital: 250));
    await tester.pumpAndSettle();
    expect(find.text('0'), findsOneWidget);
    expect(find.text('250.00 EUR'), findsOneWidget);
    expect(find.text('400.00 EUR'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    holdings.dispose();
    capital.dispose();
    service.dispose();
    preferences.dispose();
  });

  testWidgets('Dashboard switches between guest and protected My Space',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: SizedBox(height: 430, child: MySpacePanel()),
      ),
    ));
    await tester.pump();
    expect(find.byType(AuthenticatedMySpacePanel), findsOneWidget);

    session.clear();
    await tester.pump();
    expect(find.byType(AuthenticatedMySpacePanel), findsNothing);

    session.establish(accessToken: 'owner-b', account: _account(2));
    await tester.pump();
    expect(find.byType(AuthenticatedMySpacePanel), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
