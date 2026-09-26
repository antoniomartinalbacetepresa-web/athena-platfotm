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
        title: const Text('MERCADO'),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: GlobalMarketPanel(controller: controller),
        ),
      ),
    );
  }
}
