import 'package:app/core/accessibility/accessible_status_message.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('status is exposed as one live semantic announcement', (tester) async {
    final semantics = tester.ensureSemantics();
    addTearDown(semantics.dispose);

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AccessibleStatusMessage(
            message: 'La operación ha fallado.',
            semanticLabel: 'Error: la operación ha fallado.',
            style: TextStyle(),
          ),
        ),
      ),
    );

    final node = tester.getSemantics(
      find.bySemanticsLabel('Error: la operación ha fallado.'),
    );
    expect(node.flagsCollection.isLiveRegion, isTrue);
    expect(node.label, 'Error: la operación ha fallado.');
    expect(find.text('La operación ha fallado.'), findsOneWidget);
  });
}
