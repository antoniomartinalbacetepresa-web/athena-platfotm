import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../recommendations/controllers/athena_synthesis_controller.dart';
import '../../../recommendations/di/recommendation_dependencies.dart';
import '../../../recommendations/presentation/athena_synthesis_panel.dart';
import '../widgets/athena_score_panel.dart';
import '../widgets/dashboard_header.dart';
import '../widgets/market_panel.dart';
import '../widgets/my_space_panel.dart';
import '../widgets/news_panel.dart';
import '../widgets/personalized_explanation_panel.dart';
import '../widgets/recommendations_panel.dart';
import '../widgets/relevant_investors_panel.dart';
import '../widgets/system_readiness_panel.dart';

class DashboardPage extends StatefulWidget {
  final RecommendationDependencies? recommendationDependencies;

  const DashboardPage({super.key, this.recommendationDependencies});

  static const double _leftColumnWidth = 280;
  static const double _desktopBreakpoint = 1080;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  late final RecommendationDependencies _recommendationDependencies;
  late final bool _ownsRecommendationDependencies;

  AthenaSynthesisController get _synthesisController =>
      _recommendationDependencies.synthesisController;

  @override
  void initState() {
    super.initState();
    _ownsRecommendationDependencies = widget.recommendationDependencies == null;
    _recommendationDependencies = widget.recommendationDependencies ??
        RecommendationDependencies.create();
    _synthesisController.loadLatest();
  }

  @override
  void dispose() {
    if (_ownsRecommendationDependencies) {
      _recommendationDependencies.dispose();
    }
    super.dispose();
  }

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
                    const SizedBox(
                      height: 112,
                      child: SystemReadinessPanel(),
                    ),
                    const SizedBox(height: AthenaSpacing.md),
                    const PersonalizedExplanationPanel(),
                    const SizedBox(height: AthenaSpacing.md),
                    SizedBox(
                      height: 420,
                      child: AthenaSynthesisPanel(
                        controller: _synthesisController,
                      ),
                    ),
                    const SizedBox(height: AthenaSpacing.md),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        if (constraints.maxWidth < DashboardPage._desktopBreakpoint) {
                          return const _CompactDashboard();
                        }
                        return const _DesktopDashboard();
                      },
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
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 330, child: RelevantInvestorsPanel()),
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
        SizedBox(height: AthenaSpacing.md),
        SizedBox(height: 340, child: RelevantInvestorsPanel()),
      ],
    );
  }
}
