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
  static const double _desktopBreakpoint = 1080;

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
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    if (constraints.maxWidth < _desktopBreakpoint) {
                      return const _CompactDashboard();
                    }
                    return const _DesktopDashboard();
                  },
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DesktopDashboard extends StatelessWidget {
  const _DesktopDashboard();

  @override
  Widget build(BuildContext context) {
    return const Column(
      children: [
        SizedBox(
          height: 430,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: DashboardPage._leftColumnWidth,
                child: MySpacePanel(),
              ),
              SizedBox(width: AthenaSpacing.md),
              Expanded(child: RecommendationsPanel()),
            ],
          ),
        ),
        SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 400,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: DashboardPage._leftColumnWidth,
                child: AthenaScorePanel(),
              ),
              SizedBox(width: AthenaSpacing.md),
              Expanded(child: MarketPanel()),
              SizedBox(width: AthenaSpacing.md),
              Expanded(flex: 2, child: NewsPanel()),
            ],
          ),
        ),
      ],
    );
  }
}

class _CompactDashboard extends StatelessWidget {
  const _CompactDashboard();

  @override
  Widget build(BuildContext context) {
    return const Column(
      children: [
        SizedBox(height: 360, child: MySpacePanel()),
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 430, child: RecommendationsPanel()),
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 360, child: AthenaScorePanel()),
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 430, child: MarketPanel()),
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 300, child: NewsPanel()),
      ],
    );
  }
}
