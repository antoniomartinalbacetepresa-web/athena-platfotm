import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_spacing.dart';
import 'base/athena_card.dart';

class RecommendationCard extends StatelessWidget {
  final String company;
  final int score;
  final String action;
  final Color scoreColor;

  const RecommendationCard({
    super.key,
    required this.company,
    required this.score,
    required this.action,
    this.scoreColor = const Color(0xFF3DDC84),
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AthenaSpacing.md),

      child: AthenaCard(
        padding: const EdgeInsets.symmetric(
          horizontal: AthenaSpacing.md,
          vertical: AthenaSpacing.md,
        ),

        child: Row(
          children: [

            Expanded(
              child: Text(
                company,
                style: const TextStyle(
                  color: AthenaColors.text,
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),

            Text(
              action,
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 15,
              ),
            ),

            const SizedBox(width: 20),

            Container(
              width: 54,
              height: 54,

              alignment: Alignment.center,

              decoration: BoxDecoration(
                color: scoreColor.withValues(alpha: 0.15),
                shape: BoxShape.circle,
              ),

              child: Text(
                "$score",
                style: TextStyle(
                  color: scoreColor,
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}