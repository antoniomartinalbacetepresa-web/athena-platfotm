import 'package:flutter/material.dart';

import '../../../../core/routing/app_routes.dart';
import '../../../../core/theme/athena_colors.dart';
import '../../../../core/theme/athena_spacing.dart';
import '../../../auth/services/auth_session.dart';
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

typedef DashboardOperationalPanelsBuilder = Widget Function(
  int ownerEpoch,
  int marketEpoch,
  int newsEpoch,
  int investorsEpoch,
  int researchEpoch,
  int readinessEpoch,
);

class DashboardPage extends StatefulWidget {
  final RecommendationDependencies? recommendationDependencies;
  final bool renderOperationalPanels;
  /// Test composition seam; production always mounts real operational panels.
  final DashboardOperationalPanelsBuilder? operationalPanelsBuilder;

  const DashboardPage({
    super.key,
    this.recommendationDependencies,
    this.renderOperationalPanels = true,
    this.operationalPanelsBuilder,
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
  late int _observedAuthorityVersion;

  void _onSessionAuthorityChanged() {
    final version = AuthSession.instance.authorityVersion;
    if (!mounted || version == _observedAuthorityVersion) return;
    _observedAuthorityVersion = version;
    // The Dashboard can remain mounted during logout, account closure, or
    // owner replacement. Discard owner-derived panels before the next frame,
    // including when a replacement credential reuses the same token text.
    // Research and readiness may also reflect the previous owner context.
    _synthesisController.clear();
    _synthesisController.loadLatest();
    setState(() {
      _ownerRefreshEpoch++;
      _researchRefreshEpoch++;
      _readinessRefreshEpoch++;
    });
  }

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
        // Re-evaluate operational readiness after Profile/Portfolio changes.
        _readinessRefreshEpoch++;
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
    _observedAuthorityVersion = AuthSession.instance.authorityVersion;
    AuthSession.instance.addListener(_onSessionAuthorityChanged);
    _ownsRecommendationDependencies = widget.recommendationDependencies == null;
    _recommendationDependencies = widget.recommendationDependencies ??
        RecommendationDependencies.create();
    // An injected controller can already be processing a request from an
    // earlier screen. Initial mounting must establish a new request generation,
    // just as dependency replacement does in didUpdateWidget.
    if (!_ownsRecommendationDependencies) _synthesisController.clear();
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
    // An injected controller may already be loading evidence for a previous
    // mount or owner. Invalidate that request before binding this Dashboard.
    // loadLatest alone returns early while loading and would accept its result.
    _synthesisController.clear();
    _synthesisController.loadLatest();
    if (previouslyOwned) {
      previousDependencies.dispose();
    }
  }

  @override
  void dispose() {
    AuthSession.instance.removeListener(_onSessionAuthorityChanged);
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
                    if (widget.renderOperationalPanels && widget.operationalPanelsBuilder == null) ...[
                      SizedBox(
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
                    if (widget.renderOperationalPanels && widget.operationalPanelsBuilder != null)
                      widget.operationalPanelsBuilder!(
                        _ownerRefreshEpoch,
                        _marketRefreshEpoch,
                        _newsRefreshEpoch,
                        _investorsRefreshEpoch,
                        _researchRefreshEpoch,
                        _readinessRefreshEpoch,
                      ),
                    if (widget.renderOperationalPanels && widget.operationalPanelsBuilder == null) ...[
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
