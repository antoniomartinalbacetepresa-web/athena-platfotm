import 'dart:async';

import 'package:app/features/auth/models/auth_account.dart';
import 'package:app/features/auth/services/auth_session.dart';
import 'package:app/features/auth/services/auth_token_store.dart';
import 'package:app/features/dashboard/presentation/widgets/personalized_explanation_panel.dart';
import 'package:app/features/profile/models/user_personalization.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class _MemoryTokenStore implements AuthTokenStore {
  String? token;

  @override
  Future<void> deleteAccessToken() async => token = null;

  @override
  Future<String?> readAccessToken() async => token;

  @override
  Future<void> writeAccessToken(String value) async => token = value;
}

AuthAccount _account(int id) => AuthAccount(
      id: id,
      email: 'owner-$id@example.invalid',
      isActive: true,
      createdAt: DateTime.utc(2026, 10, 26),
      updatedAt: DateTime.utc(2026, 10, 26),
    );

void main() {
  UserPersonalization configured() => UserPersonalization.fromJson({
        'schema': 'athena.user-personalization.v1',
        'fingerprint': 'c' * 64,
        'presentation': {
          'detailLevel': 'technical',
          'explanationStyle': 'analytical',
          'riskEmphasis': 'high',
          'horizonEmphasis': 'long_term',
          'liquidityEmphasis': 'low',
          'objectiveFocus': 'long_term_growth',
        },
        'policy': {
          'presentationOnly': true,
          'recommendationScoringInfluence': false,
          'canonicalWeightingInfluence': false,
          'automaticLearningPromotion': false,
          'automaticTrading': false,
          'sensitiveValuesIncluded': false,
        },
      });

  Widget host(DashboardPersonalizationLoader loader) {
    return MaterialApp(
      home: Scaffold(
        body: PersonalizedExplanationPanel(loadPersonalization: loader),
      ),
    );
  }

  testWidgets('configured profile adapts explanation without financial authority',
      (tester) async {
    await tester.pumpWidget(host(() async => configured()));
    await tester.pumpAndSettle();

    expect(find.text('Tu contexto de explicación'), findsOneWidget);
    expect(find.textContaining('con detalle técnico'), findsOneWidget);
    expect(find.textContaining('con enfoque analítico'), findsOneWidget);
    expect(
      find.textContaining('priorizando riesgos y escenarios adversos'),
      findsOneWidget,
    );
    expect(find.textContaining('horizonte largo'), findsOneWidget);
    expect(find.textContaining('crecimiento a largo plazo'), findsOneWidget);
    expect(
      find.textContaining('no modifica puntuaciones, recomendaciones, ponderaciones'),
      findsOneWidget,
    );
    expect(find.textContaining('ni ejecuta operaciones'), findsOneWidget);
    expect(find.textContaining('125000'), findsNothing);
    expect(find.textContaining('EUR'), findsNothing);
  });

  testWidgets('missing profile keeps the standard explanation', (tester) async {
    await tester.pumpWidget(host(() async => null));
    await tester.pumpAndSettle();

    expect(find.text('Explicación estándar'), findsOneWidget);
    expect(find.textContaining('Configura tu perfil'), findsOneWidget);
    expect(find.text('Tu contexto de explicación'), findsNothing);
  });

  testWidgets('load failure fails closed to the standard explanation',
      (tester) async {
    await tester.pumpWidget(host(() async {
      throw const FormatException('unsafe personalization contract');
    }));
    await tester.pumpAndSettle();

    expect(find.text('Explicación estándar'), findsOneWidget);
    expect(
      find.textContaining('No se pudo verificar de forma segura'),
      findsOneWidget,
    );
    expect(find.text('Tu contexto de explicación'), findsNothing);
    expect(find.textContaining('unsafe personalization contract'), findsNothing);
  });
  testWidgets('Dashboard immediately hides previous owner explanation on switch',
      (tester) async {
    final session = AuthSession.forTesting(_MemoryTokenStore());
    session.establish(accessToken: 'owner-a', account: _account(1));
    final first = Completer<UserPersonalization?>();
    final second = Completer<UserPersonalization?>();
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PersonalizedExplanationPanel(
          session: session,
          loadPersonalization: () => ++calls == 1 ? first.future : second.future,
        ),
      ),
    ));

    first.complete(configured());
    await tester.pumpAndSettle();
    expect(find.text('Tu contexto de explicación'), findsOneWidget);

    session.establish(accessToken: 'owner-b', account: _account(2));
    await tester.pump();
    expect(find.text('Tu contexto de explicación'), findsNothing);
    expect(find.textContaining('con detalle técnico'), findsNothing);
    expect(find.textContaining('Verificando tu contexto'), findsOneWidget);

    second.complete(null);
    await tester.pumpAndSettle();
    expect(find.text('Explicación estándar'), findsOneWidget);
    expect(find.text('Tu contexto de explicación'), findsNothing);
  });

  testWidgets('late personalization response cannot restore former owner',
      (tester) async {
    final session = AuthSession.forTesting(_MemoryTokenStore());
    session.establish(accessToken: 'reused-token', account: _account(1));
    final oldResponse = Completer<UserPersonalization?>();
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: PersonalizedExplanationPanel(
          session: session,
          loadPersonalization: () =>
              ++calls == 1 ? oldResponse.future : Future.value(null),
        ),
      ),
    ));

    session.establish(accessToken: 'reused-token', account: _account(2));
    await tester.pumpAndSettle();
    expect(find.text('Explicación estándar'), findsOneWidget);
    oldResponse.complete(configured());
    await tester.pumpAndSettle();
    expect(find.text('Tu contexto de explicación'), findsNothing);
    expect(find.textContaining('con detalle técnico'), findsNothing);

    session.clear();
    await tester.pump();
    expect(find.text('Explicación estándar'), findsOneWidget);
    expect(find.textContaining('Inicia sesión'), findsOneWidget);
  });

}
