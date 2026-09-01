import 'package:flutter/material.dart';

import '../../../../../core/theme/athena_colors.dart';
import 'base/athena_card.dart';

class NewsPanel extends StatelessWidget {
  const NewsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [

          const Text(
            "NOTICIAS IA",
            style: TextStyle(
              color: AthenaColors.text,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),

          const SizedBox(height: 22),

          _news("Microsoft supera expectativas."),

          _news("La FED mantiene los tipos."),

          _news("NVIDIA presenta nuevos chips IA."),
        ],
      ),
    );
  }

  Widget _news(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),

      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,

        children: [

          const Text(
            "• ",
            style: TextStyle(
              color: AthenaColors.primary,
              fontSize: 18,
            ),
          ),

          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                color: AthenaColors.textSecondary,
                fontSize: 15,
              ),
            ),
          ),
        ],
      ),
    );
  }
}