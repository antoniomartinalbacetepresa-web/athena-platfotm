import 'package:flutter/material.dart';

import '../theme/athena_colors.dart';
import '../theme/athena_radius.dart';

class DashboardPanel extends StatelessWidget {
  final Widget child;

  const DashboardPanel({
    super.key,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AthenaColors.card,
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
        border: Border.all(
          color: AthenaColors.border,
        ),
      ),
      child: child,
    );
  }
}