import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import '../../../../../core/theme/athena_spacing.dart';
import '../../../../../core/widgets/dashboard_panel.dart';
import 'recommendation_card.dart';

class RecommendationsPanel extends StatelessWidget {
  const RecommendationsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return DashboardPanel(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(AthenaSpacing.lg),
            child: Row(
              children: [
                const Text(
                  "RECOMENDACIONES IA",
                  style: TextStyle(
                    color: AthenaColors.text,
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),

                const Spacer(),

                const Text(
                  "Actualizado hace 2 min",
                  style: TextStyle(
                    color: AthenaColors.textSecondary,
                    fontSize: 14,
                  ),
                ),
              ],
            ),
          ),

          const Divider(height: 1),

          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(AthenaSpacing.lg),
              children: const [
                RecommendationCard(
                  company: "Microsoft",
                  action: "COMPRAR",
                  score: 96,
                ),

                RecommendationCard(
                  company: "Visa",
                  action: "COMPRAR",
                  score: 94,
                ),

                RecommendationCard(
                  company: "Amazon",
                  action: "MANTENER",
                  score: 87,
                ),

                RecommendationCard(
                  company: "ASML",
                  action: "COMPRAR",
                  score: 91,
                ),

                RecommendationCard(
                  company: "Tesla",
                  action: "REDUCIR",
                  score: 62,
                ),

                RecommendationCard(
                  company: "Apple",
                  action: "COMPRAR",
                  score: 93,
                ),

                RecommendationCard(
                  company: "NVIDIA",
                  action: "MANTENER",
                  score: 89,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}