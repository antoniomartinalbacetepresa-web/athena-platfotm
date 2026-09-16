import 'package:app/features/profile/models/user_personalization.dart';
import 'package:app/features/profile/presentation/widgets/user_personalization_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  UserPersonalization configured() => UserPersonalization.fromJson({
        'schema': 'athena.user-personalization.v1',
        'fingerprint': 'b' * 64,
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

  Widget host({
    UserPersonalization? personalization,
    bool busy = false,
    String? error,
    Future<void> Function()? onReload,
  }) {
    return MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: UserPersonalizationPanel(
            personalization: personalization,
            busy: busy,
            error: error,
            onReload: onReload ?? () async {},
          ),
        ),
      ),
    );
  }

  testWidgets('configured projection is shown as presentation-only metadata',
      (tester) async {
    await tester.pumpWidget(host(personalization: configured()));

    expect(find.text('Personalización de explicaciones'), findsOneWidget);
    expect(
      find.byKey(const Key('personalization-presentation-only-note')),
      findsOneWidget,
    );
    expect(find.text('Técnico'), findsOneWidget);
    expect(find.text('Analítico'), findsOneWidget);
    expect(find.text('Largo plazo'), findsOneWidget);
    expect(find.text('Crecimiento a largo plazo'), findsOneWidget);
    expect(find.textContaining('bbbbbbbbbbbb…'), findsOneWidget);
    expect(find.textContaining('125000'), findsNothing);
    expect(find.textContaining('EUR'), findsNothing);
  });

  testWidgets('not configured and error states remain explicit and retryable',
      (tester) async {
    var reloads = 0;
    await tester.pumpWidget(host(onReload: () async => reloads += 1));

    expect(
      find.byKey(const Key('personalization-not-configured')),
      findsOneWidget,
    );
    await tester.tap(find.text('COMPROBAR'));
    await tester.pump();
    expect(reloads, 1);

    await tester.pumpWidget(host(
      error: 'Contrato rechazado.',
      onReload: () async => reloads += 1,
    ));
    await tester.pump();
    expect(find.byKey(const Key('personalization-error')), findsOneWidget);
    expect(find.text('Contrato rechazado.'), findsOneWidget);
    await tester.tap(find.text('REINTENTAR'));
    await tester.pump();
    expect(reloads, 2);
  });

  testWidgets('loading state does not render stale configured metadata',
      (tester) async {
    await tester.pumpWidget(host(personalization: configured(), busy: true));

    expect(find.byKey(const Key('personalization-loading')), findsOneWidget);
    expect(find.text('Técnico'), findsNothing);
    expect(find.byKey(const Key('personalization-contract-fingerprint')), findsNothing);
  });
}
