import 'package:app/features/dashboard/presentation/widgets/personalized_explanation_panel.dart';
import 'package:app/features/profile/models/user_personalization.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
