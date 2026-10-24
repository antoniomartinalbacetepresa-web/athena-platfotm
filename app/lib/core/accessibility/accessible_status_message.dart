import 'package:flutter/material.dart';

/// Announces asynchronous status changes to assistive technologies without
/// stealing focus from the user's current control.
class AccessibleStatusMessage extends StatelessWidget {
  const AccessibleStatusMessage({
    required this.message,
    required this.style,
    super.key,
    this.semanticLabel,
  });

  final String message;
  final TextStyle style;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      container: true,
      label: semanticLabel ?? message,
      child: ExcludeSemantics(
        child: Text(message, style: style),
      ),
    );
  }
}
