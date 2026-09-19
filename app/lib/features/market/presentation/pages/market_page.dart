import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../widgets/global_market_panel.dart';

class MarketPage extends StatelessWidget {
  const MarketPage({super.key});

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
      body: const SafeArea(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: GlobalMarketPanel(),
        ),
      ),
    );
  }
}
