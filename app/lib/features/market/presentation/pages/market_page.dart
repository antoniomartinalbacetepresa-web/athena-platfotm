import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../controllers/global_market_context_controller.dart';
import '../widgets/global_market_panel.dart';

class MarketPage extends StatelessWidget {
  final GlobalMarketContextController? controller;

  const MarketPage({super.key, this.controller});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      appBar: AppBar(
        backgroundColor: AthenaColors.background,
        foregroundColor: AthenaColors.text,
        elevation: 0,
        title: Semantics(
          header: true,
          child: const Text('MERCADO'),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Semantics(
                container: true,
                label:
                    'Contexto de mercado informativo. Los datos pueden cambiar y no constituyen una recomendación ni ejecutan operaciones.',
                child: const ExcludeSemantics(
                  child: Text(
                    'Contexto informativo: los datos pueden cambiar; no constituye una recomendación ni ejecuta operaciones.',
                    key: Key('market-information-boundary'),
                    style: TextStyle(color: AthenaColors.textSecondary),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Expanded(child: GlobalMarketPanel(controller: controller)),
            ],
          ),
        ),
      ),
    );
  }
}
