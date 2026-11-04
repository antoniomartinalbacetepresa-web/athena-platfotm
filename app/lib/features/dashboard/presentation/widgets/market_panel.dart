import 'package:flutter/material.dart';

import '../../../market/presentation/widgets/global_market_panel.dart';
import 'base/athena_card.dart';

class MarketPanel extends StatelessWidget {
  const MarketPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return const AthenaCard(
      padding: EdgeInsets.all(20),
      child: GlobalMarketPanel(),
    );
  }
}
