import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
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
  final bool renderOperationalPanels;

  const DashboardPage({
    super.key,
    this.recommendationDependencies,
    this.renderOperationalPanels = true,
  });

  static const double _leftColumnWidth = 280;
  static const double _desktopBreakpoint = 1080;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  late RecommendationDependencies _recommendationDependencies;
  late bool _ownsRecommendationDependencies;
  int _ownerRefreshEpoch = 0;

  void _onReturnFromRoute(String route) {
    if (route != AppRoutes.profile && route != AppRoutes.portfolio) return;
    if (!mounted) return;
    // Profile edits and Portfolio mutations do not change JWT authority.
    // Remount only the owner-scoped projections on return; never reuse stale
    // capital, currency, positions or explanation preferences.
    setState(() => _ownerRefreshEpoch++);
  }

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
  void didUpdateWidget(covariant DashboardPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.recommendationDependencies ==
        widget.recommendationDependencies) {
      return;
    }

    final previousDependencies = _recommendationDependencies;
    final previouslyOwned = _ownsRecommendationDependencies;
    _ownsRecommendationDependencies = widget.recommendationDependencies == null;
    _recommendationDependencies = widget.recommendationDependencies ??
        RecommendationDependencies.create();

    // The Dashboard must immediately bind to the new canonical source.
    // An old synthesis must never remain visible after dependencies change.
    _synthesisController.loadLatest();
    if (previouslyOwned) {
      previousDependencies.dispose();
    }
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
            DashboardHeader(onReturnFromRoute: _onReturnFromRoute),
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
                    if (widget.renderOperationalPanels) ...[
                      const SizedBox(
                        height: 112,
                        child: SystemReadinessPanel(),
                      ),
                      const SizedBox(height: AthenaSpacing.md),
                      PersonalizedExplanationPanel(
                        key: ValueKey('dashboard-personalization-$_ownerRefreshEpoch'),
                      ),
                      const SizedBox(height: AthenaSpacing.md),
                    ],
                    SizedBox(
                      height: 420,
                      child: AthenaSynthesisPanel(
                        controller: _synthesisController,
                      ),
                    ),
                    if (widget.renderOperationalPanels) ...[
                      const SizedBox(height: AthenaSpacing.md),
                      LayoutBuilder(
                        builder: (context, constraints) {
                          if (constraints.maxWidth < DashboardPage._desktopBreakpoint) {
                            return _CompactDashboard(ownerRefreshEpoch: _ownerRefreshEpoch);
                          }
                          return _DesktopDashboard(ownerRefreshEpoch: _ownerRefreshEpoch);
                        },
                      ),
                    ],
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
  const _DesktopDashboard({required this.ownerRefreshEpoch});

  final int ownerRefreshEpoch;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        SizedBox(
          height: 430,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: DashboardPage._leftColumnWidth,
                child: MySpacePanel(
                  key: ValueKey('dashboard-my-space-$ownerRefreshEpoch'),
                ),
              ),
              const SizedBox(width: AthenaSpacing.md),
              const Expanded(child: RecommendationsPanel()),
            ],
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(
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
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 330, child: RelevantInvestorsPanel()),
      ],
    );
  }
}

class _CompactDashboard extends StatelessWidget {
  const _CompactDashboard({required this.ownerRefreshEpoch});

  final int ownerRefreshEpoch;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        SizedBox(
          height: 360,
          child: MySpacePanel(
            key: ValueKey('dashboard-my-space-$ownerRefreshEpoch'),
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 430, child: RecommendationsPanel()),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 360, child: AthenaScorePanel()),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 430, child: MarketPanel()),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 300, child: NewsPanel()),
        const SizedBox(height: AthenaSpacing.md),
        const SizedBox(height: 340, child: RelevantInvestorsPanel()),
      ],
    );
  }
}
