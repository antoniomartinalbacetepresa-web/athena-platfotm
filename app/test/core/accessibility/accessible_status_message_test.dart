import 'package:app/core/accessibility/accessible_status_message.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('status is exposed as one live semantic announcement', (tester) async {
    final semantics = tester.ensureSemantics();

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
    expect(node.flagsCollection.contains(SemanticsFlag.isLiveRegion), isTrue);
    expect(node.label, 'Error: la operación ha fallado.');
    expect(find.text('La operación ha fallado.'), findsOneWidget);

    semantics.dispose();
  });
}
