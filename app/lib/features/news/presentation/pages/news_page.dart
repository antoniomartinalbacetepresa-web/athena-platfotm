import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../../services/athena_backend_news_synthesis_service.dart';
import '../news_synthesis_controller.dart';
import '../widgets/news_feed_panel.dart';
import '../widgets/news_synthesis_panel.dart';

class NewsPage extends StatefulWidget {
  const NewsPage({super.key});

  @override
  State<NewsPage> createState() => _NewsPageState();
}

class _NewsPageState extends State<NewsPage> {
  late final AthenaBackendNewsSynthesisService _synthesisService;
  late final NewsSynthesisController _synthesisController;

  @override
  void initState() {
    super.initState();
    _synthesisService = AthenaBackendNewsSynthesisService();
    _synthesisController = NewsSynthesisController(service: _synthesisService);
    _synthesisController.load();
  }

  @override
  void dispose() {
    _synthesisController.dispose();
    _synthesisService.dispose();
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
              const NewsFeedPanel(limit: 20),
            ],
          ),
        ),
      ),
    );
  }
}
