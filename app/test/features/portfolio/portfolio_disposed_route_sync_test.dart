import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/models/portfolio_position.dart';
import 'package:app/features/portfolio/presentation/controllers/portfolio_cloud_sync_controller.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_service.dart';
import 'package:app/features/portfolio/services/authenticated_portfolio_sync_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final session = AuthSession.instance;
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    session.clear();
  });
  tearDown(() => session.clear());

  AuthAccount account() => AuthAccount(
        id: 7,
        email: 'owner@example.com',
        displayName: 'Owner',
        isActive: true,
        createdAt: DateTime.utc(2026, 9, 10),
        updatedAt: DateTime.utc(2026, 9, 10),
      );

  PortfolioPosition position() => PortfolioPosition(
        symbol: 'AAPL',
        companyName: 'Apple Inc.',
        shares: 3,
        averagePrice: 123.45,
        currentPrice: 150,
        priceCurrency: 'USD',
        exchange: 'NASDAQ',
        currentPriceSourceProvider: 'test-market-source',
      );

  testWidgets('disposed Portfolio route cannot send a pending local snapshot', (tester) async {
    session.establish(accessToken: 'owner-token', account: account());
    final localSnapshot = Completer<List<PortfolioPosition>>();
    var networkCalled = false;
    final remote = AuthenticatedPortfolioService(
      baseUrl: 'http://athena.local',
      session: session,
      client: MockClient((_) async {
        networkCalled = true;
        return http.Response('{}', 500);
      }),
    );
    final controller = PortfolioCloudSyncController(
      service: AuthenticatedPortfolioSyncService(remoteService: remote),
    );
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AuthenticatedPortfolioPage(
        positionsLoader: () => localSnapshot.future,
        syncController: controller,
        child: const SizedBox.expand(),
      )),
    ));
    await tester.tap(find.byKey(const Key('portfolio-authenticated-sync')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    localSnapshot.complete([position()]);
    await tester.pumpAndSettle();
    expect(networkCalled, isFalse);
    expect(controller.status, PortfolioCloudSyncStatus.idle);
    controller.dispose();
    remote.dispose();
  });

}
