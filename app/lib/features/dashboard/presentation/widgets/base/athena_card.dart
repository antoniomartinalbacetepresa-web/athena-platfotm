import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_radius.dart';
import '../../../../../core/theme/athena_spacing.dart';

class AthenaCard extends StatelessWidget {
  final Widget child;

  final EdgeInsetsGeometry? padding;

  final VoidCallback? onTap;

  const AthenaCard({
    super.key,
    required this.child,
    this.padding,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    Widget card = AnimatedContainer(
      duration: const Duration(milliseconds: 180),

      padding: padding ??
          const EdgeInsets.all(
            AthenaSpacing.lg,
          ),

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

    if (onTap != null) {
      return InkWell(
        borderRadius: BorderRadius.circular(
          AthenaRadius.lg,
        ),
        onTap: onTap,
        child: card,
      );
    }

    return card;
  }
}