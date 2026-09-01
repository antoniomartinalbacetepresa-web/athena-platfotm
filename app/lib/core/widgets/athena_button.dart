import 'package:flutter/material.dart';

import '../theme/athena_colors.dart';
import '../theme/athena_radius.dart';
import '../theme/athena_spacing.dart';
import '../typography/athena_text.dart';

class AthenaButton extends StatelessWidget {
  final String text;
  final VoidCallback onPressed;
  final IconData? icon;

  const AthenaButton({
    super.key,
    required this.text,
    required this.onPressed,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,

      child: ElevatedButton(
        onPressed: onPressed,

        style: ElevatedButton.styleFrom(
          backgroundColor: AthenaColors.primary,
          foregroundColor: Colors.white,

          elevation: 0,

          padding: const EdgeInsets.symmetric(
            horizontal: AthenaSpacing.lg,
          ),

          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(
              AthenaRadius.md,
            ),
          ),
        ),

        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,

          mainAxisSize: MainAxisSize.min,

          children: [

            if (icon != null) ...[
              Icon(
                icon,
                size: 18,
              ),

              const SizedBox(width: 8),
            ],

            Text(
              text,
              style: AthenaText.title.copyWith(
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}