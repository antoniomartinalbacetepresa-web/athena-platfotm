import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../widgets/athena_score_panel.dart';
import '../widgets/dashboard_header.dart';
import '../widgets/market_panel.dart';
import '../widgets/my_space_panel.dart';
import '../widgets/news_panel.dart';
import '../widgets/recommendations_panel.dart';

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  static const double _leftColumnWidth = 280;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AthenaColors.background,
      body: SafeArea(
        child: Column(
          children: [
            const DashboardHeader(),

            const SizedBox(height: AthenaSpacing.md),

            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(
                  AthenaSpacing.md,
                  0,
                  AthenaSpacing.md,
                  AthenaSpacing.lg,
                ),
                child: Column(
                  children: [
                    SizedBox(
                      height: 430,
                      child: Row(
                        crossAxisAlignment:
                            CrossAxisAlignment.stretch,
                        children: [
                          const SizedBox(
                            width: _leftColumnWidth,
                            child: MySpacePanel(),
                          ),

                          const SizedBox(
                            width: AthenaSpacing.md,
                          ),

                          const Expanded(
                            child: RecommendationsPanel(),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(
                      height: AthenaSpacing.md,
                    ),

                    SizedBox(
                      height: 400,
                      child: Row(
                        crossAxisAlignment:
                            CrossAxisAlignment.stretch,
                        children: [
                          const SizedBox(
                            width: _leftColumnWidth,
                            child: AthenaScorePanel(),
                          ),

                          const SizedBox(
                            width: AthenaSpacing.md,
                          ),

                          const Expanded(
                            child: MarketPanel(),
                          ),

                          const SizedBox(
                            width: AthenaSpacing.md,
                          ),

                          const Expanded(
                            flex: 2,
                            child: NewsPanel(),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}