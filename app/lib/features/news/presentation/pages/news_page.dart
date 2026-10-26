import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../models/verified_news_feed.dart';
import '../../services/athena_backend_news_synthesis_service.dart';
import '../news_synthesis_controller.dart';
import '../widgets/news_feed_panel.dart';
import '../widgets/news_synthesis_panel.dart';

class NewsPage extends StatefulWidget {
  final NewsSynthesisController? synthesisController;
  final Widget? newsFeed;
  final Future<VerifiedNewsFeed> Function(int limit)? feedLoader;

  const NewsPage({
    super.key,
    this.synthesisController,
    this.newsFeed,
    this.feedLoader,
  });

  @override
  State<NewsPage> createState() => _NewsPageState();
}

class _NewsPageState extends State<NewsPage> {
  AthenaBackendNewsSynthesisService? _ownedSynthesisService;
  late NewsSynthesisController _synthesisController;
  late bool _ownsSynthesisController;
  int _feedRefreshEpoch = 0;

  void _refreshAllEvidence() {
    if (!mounted) return;
    // News synthesis and the independently verified feed are different sources.
    // Invalidate both; neither a late synthesis nor a late feed may survive.
    _synthesisController.clear();
    _synthesisController.load();
    setState(() => _feedRefreshEpoch++);
  }

  @override
  void initState() {
    super.initState();
    _ownsSynthesisController = widget.synthesisController == null;
    if (_ownsSynthesisController) {
      _ownedSynthesisService = AthenaBackendNewsSynthesisService();
      _synthesisController = NewsSynthesisController(
        service: _ownedSynthesisService!,
      );
    } else {
      _synthesisController = widget.synthesisController!;
    }
    _synthesisController.load();
  }

  @override
  void didUpdateWidget(covariant NewsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.synthesisController == widget.synthesisController) return;

    final previousController = _synthesisController;
    final previousService = _ownedSynthesisService;
    final previouslyOwned = _ownsSynthesisController;

    _ownsSynthesisController = widget.synthesisController == null;
    if (_ownsSynthesisController) {
      _ownedSynthesisService = AthenaBackendNewsSynthesisService();
      _synthesisController = NewsSynthesisController(
        service: _ownedSynthesisService!,
      );
    } else {
      _ownedSynthesisService = null;
      _synthesisController = widget.synthesisController!;
    }

    // Rebind immediately: never render the former controller's synthesis.
    _synthesisController.load();
    if (previouslyOwned) {
      previousController.dispose();
      previousService?.dispose();
    }
  }

  @override
  void dispose() {
    if (_ownsSynthesisController) {
      _synthesisController.dispose();
      _ownedSynthesisService?.dispose();
    }
    super.dispose();
  }

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
          child: Text('NOTICIAS', key: Key('news-page-heading')),
        ),
        actions: [
          IconButton(
            key: const Key('news-page-refresh-all'),
            tooltip: 'Actualizar noticias y análisis ATHENA',
            onPressed: _refreshAllEvidence,
            icon: const Icon(Icons.sync),
          ),
          IconButton(
            key: const Key('news-page-refresh-synthesis'),
            tooltip: 'Actualizar análisis ATHENA de noticias',
            onPressed: () {
              // Invalidate a pending synthesis before requesting fresh evidence.
              _synthesisController.clear();
              _synthesisController.load();
            },
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              NewsSynthesisPanel(controller: _synthesisController),
              const SizedBox(height: 24),
              widget.newsFeed ?? NewsFeedPanel(
                key: ValueKey('news-page-feed-$_feedRefreshEpoch'),
                limit: 20,
                shrinkWrap: true,
                loadFeed: widget.feedLoader,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
