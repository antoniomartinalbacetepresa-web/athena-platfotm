import 'package:flutter/material.dart';

import '../../../../core/theme/athena_colors.dart';
import '../widgets/news_feed_panel.dart';

class NewsPage extends StatelessWidget {
  const NewsPage({super.key});

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
      body: const SafeArea(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: NewsFeedPanel(limit: 20),
        ),
      ),
    );
  }
}
