import 'dart:convert';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/portfolio/presentation/pages/authenticated_portfolio_page.dart';
import 'package:app/features/portfolio/presentation/pages/portfolio_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'portfolio': jsonEncode({
        'id': 'local-only',
        'name': 'Local stale portfolio',
        'initialCapital': 5000,
        'positions': [
          {
            'symbol': 'LOCAL',
            'companyName': 'Must never leak into authenticated account',
            'shares': 99,
            'averagePrice': 1,
            'currentPrice': 1,
          }
        ],
      }),
    });
    await AuthSession.instance.clearAfterRemoteInvalidation();
  });

  tearDown(() async {
    await AuthSession.instance.clearAfterRemoteInvalidation();
  });

  testWidgets('guest product boundary remains explicitly local', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: AuthenticatedPortfolioPage()),
    );
    await tester.pumpAndSettle();

    expect(find.byType(PortfolioPage), findsOneWidget);
    expect(find.text('Must never leak into authenticated account'), findsOneWidget);
  });

  testWidgets(
    'authenticated product boundary never mounts local PortfolioPage or exposes local holdings',
    (tester) async {
      AuthSession.instance.establish(
        accessToken: 'authenticated-token',
        account: AuthAccount(
          id: 42,
          email: 'owner@example.com',
          displayName: 'Owner',
          isActive: true,
          createdAt: DateTime.parse('2026-09-15T10:00:00Z'),
          updatedAt: DateTime.parse('2026-09-15T10:00:00Z'),
        ),
      );

      await tester.pumpWidget(
        const MaterialApp(home: AuthenticatedPortfolioPage()),
      );
      await tester.pump();

      expect(find.byType(PortfolioPage), findsNothing);
      expect(find.text('Must never leak into authenticated account'), findsNothing);
      expect(
        find.text('Posiciones personales protegidas por tu cuenta ATHENA'),
        findsOneWidget,
      );
      expect(find.byKey(const Key('portfolio-authenticated-history')), findsOneWidget);

      // The real backend may be unavailable in a widget test. That must become
      // an explicit authoritative error/empty state, never a local fallback.
      await tester.pumpAndSettle(const Duration(milliseconds: 50));
      expect(find.byType(PortfolioPage), findsNothing);
      expect(find.text('Must never leak into authenticated account'), findsNothing);
    },
  );
}