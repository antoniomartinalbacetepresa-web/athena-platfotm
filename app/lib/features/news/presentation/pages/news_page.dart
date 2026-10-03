import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../services/athena_backend_news_synthesis_service.dart';
import '../news_synthesis_controller.dart';
import '../widgets/news_feed_panel.dart';
import '../widgets/news_synthesis_panel.dart';

class NewsPage extends StatefulWidget {
  final NewsSynthesisController? synthesisController;
  final Widget? newsFeed;

  const NewsPage({
    super.key,
    this.synthesisController,
    this.newsFeed,
  });

  @override
  State<NewsPage> createState() => _NewsPageState();
}

class _NewsPageState extends State<NewsPage> {
  AthenaBackendNewsSynthesisService? _ownedSynthesisService;
  late final NewsSynthesisController _synthesisController;
  late final bool _ownsSynthesisController;

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
        title: const Text('NOTICIAS'),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              NewsSynthesisPanel(controller: _synthesisController),
              const SizedBox(height: 24),
              widget.newsFeed ?? const NewsFeedPanel(limit: 20),
            ],
          ),
        ),
      ),
    );
  }
}
