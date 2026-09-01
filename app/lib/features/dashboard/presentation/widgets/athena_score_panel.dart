import 'package:flutter/material.dart';

import '../../../../../core/typography/athena_text.dart';
import 'base/athena_card.dart';

class AthenaScorePanel extends StatelessWidget {
  const AthenaScorePanel({super.key});

  @override
  Widget build(BuildContext context) {
    return AthenaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'ATHENA SCORE',
            style: AthenaText.h3,
          ),

          const SizedBox(height: 10),

          const Expanded(
            child: Center(
              child: CircleAvatar(
                radius: 42,
                backgroundColor: Color(0xFF1D3B5E),
                child: Text(
                  '92',
                  style: AthenaText.score,
                ),
              ),
            ),
          ),

          const Center(
            child: Text(
              'Excelente',
              style: AthenaText.title,
            ),
          ),

          const SizedBox(height: 10),

          const Divider(),

          const SizedBox(height: 8),

          const Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Riesgo',
                style: AthenaText.caption,
              ),
              Text(
                'Bajo',
                style: TextStyle(
                  color: Color(0xFF45D483),
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),

          const SizedBox(height: 6),

          const Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Potencial',
                style: AthenaText.caption,
              ),
              Text(
                'Alto',
                style: TextStyle(
                  color: Color(0xFF45D483),
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}