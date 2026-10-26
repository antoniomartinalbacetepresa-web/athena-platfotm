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
  int _marketRefreshEpoch = 0;
  int _newsRefreshEpoch = 0;
  int _investorsRefreshEpoch = 0;
  int _researchRefreshEpoch = 0;
  int _readinessRefreshEpoch = 0;

  void _refreshAll() {
    if (!mounted) return;
    // A refresh invalidates any pending canonical response before new evidence
    // is requested. The independent panels are recreated from their sources.
    _synthesisController.clear();
    _synthesisController.loadLatest();
    setState(() {
      _ownerRefreshEpoch++;
      _marketRefreshEpoch++;
      _newsRefreshEpoch++;
      _investorsRefreshEpoch++;
      _researchRefreshEpoch++;
      _readinessRefreshEpoch++;
    });
  }

  void _onReturnFromRoute(String route) {
    if (!mounted) return;
    if (route == AppRoutes.profile || route == AppRoutes.portfolio) {
      // Owner edits do not necessarily rotate JWT authority.
      setState(() {
        _ownerRefreshEpoch++;
        // Owner edits can change portfolio-dependent research eligibility.
        _researchRefreshEpoch++;
      });
      return;
    }
    if (route != AppRoutes.market && route != AppRoutes.news) return;
    // Public evidence may have changed while Dashboard was hidden.
    // Clear the previous synthesis and invalidate any in-flight request.
    _synthesisController.clear();
    _synthesisController.loadLatest();
    setState(() {
      // Research and readiness may change with new market/news evidence.
      _researchRefreshEpoch++;
      _readinessRefreshEpoch++;
      if (route == AppRoutes.market) {
        _marketRefreshEpoch++;
      } else {
        _newsRefreshEpoch++;
      }
    });
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
            DashboardHeader(
              onReturnFromRoute: _onReturnFromRoute,
              onRefresh: _refreshAll,
            ),
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
                        child: SystemReadinessPanel(
                          key: ValueKey('dashboard-readiness-$_readinessRefreshEpoch'),
                        ),
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
                            return _CompactDashboard(
                              ownerRefreshEpoch: _ownerRefreshEpoch,
                              marketRefreshEpoch: _marketRefreshEpoch,
                              newsRefreshEpoch: _newsRefreshEpoch,
                              investorsRefreshEpoch: _investorsRefreshEpoch,
                              researchRefreshEpoch: _researchRefreshEpoch,
                            );
                          }
                          return _DesktopDashboard(
                            ownerRefreshEpoch: _ownerRefreshEpoch,
                            marketRefreshEpoch: _marketRefreshEpoch,
                            newsRefreshEpoch: _newsRefreshEpoch,
                              investorsRefreshEpoch: _investorsRefreshEpoch,
                              researchRefreshEpoch: _researchRefreshEpoch,
                          );
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
  const _DesktopDashboard({
    required this.ownerRefreshEpoch,
    required this.marketRefreshEpoch,
    required this.newsRefreshEpoch,
    required this.investorsRefreshEpoch,
    required this.researchRefreshEpoch,
  });

  final int ownerRefreshEpoch;
  final int marketRefreshEpoch;
  final int newsRefreshEpoch;
  final int investorsRefreshEpoch;
  final int researchRefreshEpoch;

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
              Expanded(
                child: RecommendationsPanel(
                  key: ValueKey('dashboard-recommendations-$researchRefreshEpoch'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 400,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                width: DashboardPage._leftColumnWidth,
                child: AthenaScorePanel(
                  key: ValueKey('dashboard-score-$researchRefreshEpoch'),
                ),
              ),
              SizedBox(width: AthenaSpacing.md),
              Expanded(
                child: MarketPanel(
                  key: ValueKey('dashboard-market-$marketRefreshEpoch'),
                ),
              ),
              SizedBox(width: AthenaSpacing.md),
              Expanded(
                flex: 2,
                child: NewsPanel(
                  key: ValueKey('dashboard-news-$newsRefreshEpoch'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 330,
          child: RelevantInvestorsPanel(
            key: ValueKey('dashboard-investors-$investorsRefreshEpoch'),
          ),
        ),
      ],
    );
  }
}

class _CompactDashboard extends StatelessWidget {
  const _CompactDashboard({
    required this.ownerRefreshEpoch,
    required this.marketRefreshEpoch,
    required this.newsRefreshEpoch,
    required this.investorsRefreshEpoch,
    required this.researchRefreshEpoch,
  });

  final int ownerRefreshEpoch;
  final int marketRefreshEpoch;
  final int newsRefreshEpoch;
  final int investorsRefreshEpoch;
  final int researchRefreshEpoch;

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
        SizedBox(
          height: 430,
          child: RecommendationsPanel(
            key: ValueKey('dashboard-recommendations-$researchRefreshEpoch'),
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 360,
          child: AthenaScorePanel(
            key: ValueKey('dashboard-score-$researchRefreshEpoch'),
          ),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 430,
          child: MarketPanel(key: ValueKey('dashboard-market-$marketRefreshEpoch')),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 300,
          child: NewsPanel(key: ValueKey('dashboard-news-$newsRefreshEpoch')),
        ),
        const SizedBox(height: AthenaSpacing.md),
        SizedBox(
          height: 340,
          child: RelevantInvestorsPanel(
            key: ValueKey('dashboard-investors-$investorsRefreshEpoch'),
          ),
        ),
      ],
    );
  }
}
